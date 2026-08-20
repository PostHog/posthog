import { parseJSON } from '~/common/utils/json-parse'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { UrlDropReason } from './metrics'
import { isPublicHost, politenessKey } from './politeness-key'

/** Beyond this the URL is not something the mirror produced, so it is a format disagreement. */
const MAX_URL_LENGTH = 2048

/**
 * A record holds one domain from one message, and the collector caps a message at 512, so a
 * well-formed record stays under this. The headroom is small on purpose, because crawl-history
 * request fan-out and the in-memory candidate set both scale with this value.
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
    /** Moves this URL may still make. A republish and a retry each spend one. Requirement 11. */
    hopsRemaining: number
    /** The lane must not fetch this URL before this epoch ms. Zero means now. Requirement 15. */
    notBeforeMs: number
}

/**
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
 * The producer and this consumer ship from separate deployments, so a record can arrive from a
 * mirror older or newer than this code. This checks every field rather than trusts it, and it counts
 * and drops a record that does not parse instead of throwing, because one bad record must not stall
 * the partition it shares with every other site.
 *
 * `domain` comes from the Kafka key, because the key routed the record to this partition, so the key
 * is what the politeness budget must be scoped to.
 */
export function parseCollectedUrlsRecord(value: Buffer | null, key: string | null): RecordParse {
    if (!value || !key) {
        return { ok: false, reason: 'malformed' }
    }
    // Normalized once here, because the budget, the metrics, and the republish key all read it. A
    // record written before the producer stripped the trailing dot carries the dotted spelling, and
    // two spellings of one domain would take two budgets on the same pod.
    const domain = withoutTrailingDot(key)
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
        // The connection layer refuses a private address, so this is not the only guard against
        // one. It is the only guard against a name that looks internal and resolves to a public
        // address, because no address check can refuse that. Requirement 35.
        if (!isPublicHost(withoutTrailingDot(host))) {
            rejected.push({ reason: 'private_host' })
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
            domain,
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
 * The key must be the registrable domain of the host, not merely a domain the host sits under. A key
 * of `cdn.example.com` would give that subdomain a rate budget of its own, and a producer that
 * writes one key for each subdomain would hand one operator a multiple of the rate we promise it.
 * The key also decides the partition, so a record that fails this test is on the wrong partition as
 * well. Requirement 3.
 *
 * This drops the trailing dot first. `example.com.` and `example.com` name the same host, and a
 * record written before the producer stripped the dot carries the dotted form.
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
        // the wire in clear text, and requirement 9 keeps a redirect off HTTP only if the first URL
        // is HTTPS.
        if (parsed.protocol !== 'https:' || parsed.hostname !== host) {
            return false
        }
        // The lane refuses both on a redirect target, so it holds the first hop to the same rule. A
        // port other than the scheme's own would make this lane a port prober, and userinfo is a
        // credential this lane never sends. The canonicalizer strips both, so this checks against a
        // wrong or stale producer rather than an expected case.
        return parsed.port === '' && !parsed.username && !parsed.password
    } catch {
        return false
    }
}
