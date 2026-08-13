import { parseJSON } from '~/common/utils/json-parse'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { UrlDropReason } from './metrics'
import { politenessKey } from './politeness-key'

/** Beyond this the URL is not something the mirror produced, so it is a format disagreement. */
const MAX_URL_LENGTH = 2048

/**
 * A record holds one domain from one message, and the collector caps a message at 512, so a
 * well-formed record stays under this. Headroom is deliberately small: the Redis round trips of a
 * batch scale with this value and run one after another inside one batch budget.
 */
const MAX_URLS_PER_RECORD = 640

export interface FetchCandidate {
    ref: string
    urlHash: string
    url: string
    host: string
    domain: string
    pseudoTeam: string
    capturedAtMs: number
    /** Moves this URL may still make. A redirect, a republish, and a retry each spend one. Requirement 11. */
    hopsRemaining: number
    /** Epoch ms before which this URL must not be fetched. Zero means now. Requirement 15. */
    notBeforeMs: number
}

/**
 * A URL may move this many times before the lane gives up on it.
 *
 * One budget rather than one counter for redirects and another for retries, because a chain that
 * alternates between the two would otherwise never end. Requirement 11.
 */
export const MAX_HOPS = 10

export type RecordParse =
    | { ok: true; candidates: FetchCandidate[]; urlCount: number; rejected: { reason: UrlDropReason }[] }
    | { ok: false; reason: Extract<UrlDropReason, 'malformed' | 'unsupported_version' | 'oversized_record'> }

function isStringRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Read one record off the fetch topic.
 *
 * The producer and this consumer ship from separate deployments, so a record can arrive from a
 * mirror older or newer than this code. Every field is therefore checked rather than trusted, and a
 * record that does not parse is counted and dropped instead of throwing: one bad record must not
 * stall the partition it shares with every other site.
 *
 * `domain` comes from the Kafka key, because the key is what routed the record to this partition and
 * so is what the politeness budget must be scoped to.
 */
export function parseCollectedUrlsRecord(value: Buffer | null, key: string | null): RecordParse {
    if (!value || !key) {
        return { ok: false, reason: 'malformed' }
    }
    let parsed: unknown
    try {
        parsed = parseJSON(value.toString())
    } catch {
        return { ok: false, reason: 'malformed' }
    }
    if (!isStringRecord(parsed)) {
        return { ok: false, reason: 'malformed' }
    }
    if (parsed.v !== 1) {
        return { ok: false, reason: 'unsupported_version' }
    }
    const { pseudoTeam, capturedAtMs, urls, hopsRemaining, notBeforeMs } = parsed
    if (typeof pseudoTeam !== 'string' || !pseudoTeam || typeof capturedAtMs !== 'number' || !Array.isArray(urls)) {
        return { ok: false, reason: 'malformed' }
    }
    // Finite, not merely a number: JSON carries `-1e400`, which parses to -Infinity and would reach
    // a histogram as an infinite age. prom-client throws on that, and a throw here stops the
    // consumer and replays the same record forever.
    if (!Number.isFinite(capturedAtMs)) {
        return { ok: false, reason: 'malformed' }
    }
    if (urls.length > MAX_URLS_PER_RECORD) {
        return { ok: false, reason: 'oversized_record' }
    }

    // Absent means a record straight from the mirror, which has made no moves and may go now. Both
    // fields are optional additions rather than a new version, so a consumer that predates them
    // reads such a record as it always did: full budget, fetch immediately.
    const hops = clampHops(hopsRemaining)
    const notBefore = typeof notBeforeMs === 'number' && Number.isFinite(notBeforeMs) ? notBeforeMs : 0

    const candidates: FetchCandidate[] = []
    const rejected: { reason: UrlDropReason }[] = []
    for (const entry of urls) {
        if (!isStringRecord(entry) || typeof entry.ref !== 'string' || typeof entry.url !== 'string') {
            rejected.push({ reason: 'bad_ref' })
            continue
        }
        const ref = parseImageRef(entry.ref)
        if (!ref || ref.source !== 'url' || ref.pseudoTeam !== pseudoTeam) {
            rejected.push({ reason: 'bad_ref' })
            continue
        }
        const host = typeof entry.host === 'string' ? entry.host : ''
        if (!isFetchableUrl(entry.url, host)) {
            rejected.push({ reason: 'bad_url' })
            continue
        }
        if (!hostIsKeyedByItsOperator(host, key)) {
            rejected.push({ reason: 'foreign_domain' })
            continue
        }
        candidates.push({
            ref: entry.ref,
            urlHash: ref.hash,
            url: entry.url,
            host,
            domain: key,
            pseudoTeam,
            capturedAtMs,
            hopsRemaining: hops,
            notBeforeMs: notBefore,
        })
    }
    return { ok: true, candidates, urlCount: urls.length, rejected }
}

/** A record naming more hops than the budget allows is treated as a full budget, so a bad producer cannot buy itself extra trips. */
function clampHops(value: unknown): number {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        return MAX_HOPS
    }
    return Math.max(0, Math.min(MAX_HOPS, Math.floor(value)))
}

/**
 * The key must be the registrable domain of the host, not merely a domain the host sits under.
 *
 * A key of `cdn.example.com` would give that subdomain a rate budget of its own, and a producer
 * writing one key per subdomain would hand one operator a multiple of the rate we promise it. The
 * key also decides the partition, so a record failing this test is on the wrong partition as well.
 * Requirement 3.
 *
 * The trailing dot is dropped from the key first. `example.com.` and `example.com` name the same
 * host, and a record written before the producer stripped it carries the dotted form.
 */
function hostIsKeyedByItsOperator(host: string, key: string): boolean {
    return politenessKey(withoutTrailingDot(host)) === withoutTrailingDot(key)
}

function withoutTrailingDot(value: string): string {
    return value.endsWith('.') ? value.slice(0, -1) : value
}

/**
 * The mirror already applied the full URL policy before producing, so this repeats only the checks
 * that a wrong or stale producer could get past. It is not the SSRF gate: that belongs immediately
 * before a request goes out, against the host of every redirect, and no request goes out here.
 */
function isFetchableUrl(url: string, host: string): boolean {
    if (url.length > MAX_URL_LENGTH || !host) {
        return false
    }
    try {
        const parsed = new URL(url)
        // HTTPS only, which is what the collector produces. A plain HTTP URL would put an image on
        // the wire in clear text, and requirement 9 then has nothing to allow a redirect down to.
        if (parsed.protocol !== 'https:' || parsed.hostname !== host) {
            return false
        }
        // Both of these are refused on a redirect target, so the first hop is held to the same rule.
        // A port other than the scheme's own would make this lane a port prober, and userinfo is a
        // credential this lane never sends. The canonicalizer strips both, which is why this is a
        // check against a wrong or stale producer rather than an expected case.
        return parsed.port === '' && !parsed.username && !parsed.password
    } catch {
        return false
    }
}
