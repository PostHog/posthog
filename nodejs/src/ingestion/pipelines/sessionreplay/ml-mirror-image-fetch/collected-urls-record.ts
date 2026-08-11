import { parseJSON } from '~/common/utils/json-parse'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { UrlDropReason } from './metrics'

/** Beyond this the URL is not something the mirror produced, so it is a format disagreement. */
const MAX_URL_LENGTH = 2048

const FETCHABLE_SCHEMES = new Set(['http:', 'https:'])

/**
 * The producer splits a record at 64 URLs. A record above this came from a producer that does not
 * agree with this one, and its size drives a Redis pipeline and a batch's memory, so it is refused
 * rather than trusted.
 */
const MAX_URLS_PER_RECORD = 128

export interface FetchCandidate {
    ref: string
    urlHash: string
    url: string
    host: string
    domain: string
    pseudoTeam: string
    capturedAtMs: number
}

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
 * `domain` comes from the Kafka key rather than the record body, because the key is what routed the
 * record to this partition and so is what the politeness budget must be scoped to.
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
    const { pseudoTeam, capturedAtMs, urls } = parsed
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
        // The key is what the per-site budget is scoped to, so a host outside it would be rate
        // limited against another site's allowance.
        if (!hostBelongsToDomain(host, key)) {
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
        })
    }
    return { ok: true, candidates, urlCount: urls.length, rejected }
}

function hostBelongsToDomain(host: string, domain: string): boolean {
    return host === domain || host.endsWith(`.${domain}`)
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
        return FETCHABLE_SCHEMES.has(parsed.protocol) && parsed.hostname === host
    } catch {
        return false
    }
}
