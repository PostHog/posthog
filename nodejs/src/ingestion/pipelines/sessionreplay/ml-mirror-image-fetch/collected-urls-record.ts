import { parseJSON } from '~/common/utils/json-parse'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { canonicalizeUrl } from './politeness-key'

export const MAX_HOPS = 10
export const MAX_JOBS_PER_RECORD = 1_000
export const MAX_RECORD_BYTES = 512 * 1024

export type UrlDropReason =
    | 'malformed'
    | 'unsupported_version'
    | 'bad_ref'
    | 'bad_url'
    | 'foreign_domain'
    | 'oversized_record'
export type RepublishReason =
    | 'redirect'
    | 'retry'
    | 'not_ready'
    | 'pass_deadline'
    | 'origin_map_full'
    | 'registrable_domain_map_full'

export interface FetchCandidate {
    originalRef: string
    currentUrl: string
    host: string
    origin: string
    registrableDomain: string
    remainingHops: number
    notBeforeMs: number
    firstSeenAtMs: number
    fetchCount: number
    republishCount: number
    lastRepublishReason: RepublishReason | null
}

export interface FrontierRecord {
    v: 2
    jobs: Array<
        Pick<
            FetchCandidate,
            | 'originalRef'
            | 'currentUrl'
            | 'remainingHops'
            | 'notBeforeMs'
            | 'firstSeenAtMs'
            | 'fetchCount'
            | 'republishCount'
            | 'lastRepublishReason'
        >
    >
}

export type RecordParse =
    | { ok: true; candidates: FetchCandidate[]; urlCount: number; rejected: { reason: UrlDropReason }[] }
    | {
          ok: false
          reason: Extract<
              UrlDropReason,
              'malformed' | 'unsupported_version' | 'oversized_record' | 'bad_ref' | 'bad_url' | 'foreign_domain'
          >
      }

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonNegativeSafeInteger(value: unknown): value is number {
    return Number.isSafeInteger(value) && (value as number) >= 0
}

function isRepublishReason(value: unknown): value is RepublishReason | null {
    return (
        value === null ||
        value === 'redirect' ||
        value === 'retry' ||
        value === 'not_ready' ||
        value === 'pass_deadline' ||
        value === 'origin_map_full' ||
        value === 'registrable_domain_map_full'
    )
}

export function parseCollectedUrlsRecord(value: Buffer | null, key: string | null): RecordParse {
    if (!value || !key) {
        return { ok: false, reason: 'malformed' }
    }
    if (value.length > MAX_RECORD_BYTES) {
        return { ok: false, reason: 'oversized_record' }
    }

    let parsed: unknown
    try {
        parsed = parseJSON(value.toString())
    } catch {
        return { ok: false, reason: 'malformed' }
    }
    if (!isRecord(parsed)) {
        return { ok: false, reason: 'malformed' }
    }
    if (parsed.v === 1 && Array.isArray(parsed.urls)) {
        return parseLegacyRecord(parsed, key)
    }
    if (parsed.v !== 2 && !(parsed.v === 1 && Array.isArray(parsed.jobs))) {
        return { ok: false, reason: 'unsupported_version' }
    }
    if (!Array.isArray(parsed.jobs) || parsed.jobs.length === 0) {
        return { ok: false, reason: 'malformed' }
    }
    if (parsed.jobs.length > MAX_JOBS_PER_RECORD) {
        return { ok: false, reason: 'oversized_record' }
    }

    const candidates: FetchCandidate[] = []
    const rejected: { reason: UrlDropReason }[] = []
    for (const job of parsed.jobs) {
        const parsedJob = parseJob(job, key)
        if (!parsedJob.ok) {
            return { ok: false, reason: parsedJob.reason }
        }
        candidates.push(parsedJob.candidate)
    }
    return { ok: true, candidates, urlCount: parsed.jobs.length, rejected }
}

function parseLegacyRecord(parsed: Record<string, unknown>, kafkaKey: string): RecordParse {
    const { pseudoTeam, capturedAtMs, urls, hopsRemaining, notBeforeMs } = parsed
    if (
        typeof pseudoTeam !== 'string' ||
        pseudoTeam.length === 0 ||
        !isNonNegativeSafeInteger(capturedAtMs) ||
        !Array.isArray(urls) ||
        urls.length === 0
    ) {
        return { ok: false, reason: 'malformed' }
    }
    if (urls.length > MAX_JOBS_PER_RECORD) {
        return { ok: false, reason: 'oversized_record' }
    }
    const remainingHops = isNonNegativeSafeInteger(hopsRemaining) ? Math.min(hopsRemaining, MAX_HOPS) : MAX_HOPS
    const readyAtMs = isNonNegativeSafeInteger(notBeforeMs) ? notBeforeMs : 0
    const candidates: FetchCandidate[] = []
    const rejected: { reason: UrlDropReason }[] = []
    for (const entry of urls) {
        if (!isRecord(entry) || typeof entry.ref !== 'string' || typeof entry.url !== 'string') {
            rejected.push({ reason: 'bad_url' })
            continue
        }
        const ref = parseImageRef(entry.ref)
        if (!ref || ref.source !== 'url' || ref.pseudoTeam !== pseudoTeam) {
            rejected.push({ reason: 'bad_ref' })
            continue
        }
        const canonical = canonicalizeUrl(entry.url)
        if (!canonical) {
            rejected.push({ reason: 'bad_url' })
            continue
        }
        if (canonical.domain !== kafkaKey.replace(/\.$/, '')) {
            rejected.push({ reason: 'foreign_domain' })
            continue
        }
        candidates.push({
            originalRef: entry.ref,
            currentUrl: canonical.fetch,
            host: canonical.host,
            origin: new URL(canonical.fetch).origin,
            registrableDomain: canonical.domain,
            remainingHops,
            notBeforeMs: readyAtMs,
            firstSeenAtMs: capturedAtMs,
            fetchCount: 0,
            republishCount: 0,
            lastRepublishReason: null,
        })
    }
    return { ok: true, candidates, urlCount: urls.length, rejected }
}

function parseJob(
    job: unknown,
    kafkaKey: string
):
    | { ok: true; candidate: FetchCandidate }
    | { ok: false; reason: Extract<UrlDropReason, 'bad_ref' | 'bad_url' | 'foreign_domain'> } {
    if (!isRecord(job)) {
        return { ok: false, reason: 'bad_url' }
    }
    const {
        originalRef,
        currentUrl,
        remainingHops,
        notBeforeMs,
        firstSeenAtMs,
        fetchCount,
        republishCount,
        lastRepublishReason,
    } = job
    if (
        typeof originalRef !== 'string' ||
        typeof currentUrl !== 'string' ||
        !isNonNegativeSafeInteger(remainingHops) ||
        remainingHops > MAX_HOPS ||
        !isNonNegativeSafeInteger(notBeforeMs) ||
        !isNonNegativeSafeInteger(firstSeenAtMs) ||
        !isNonNegativeSafeInteger(fetchCount) ||
        !isNonNegativeSafeInteger(republishCount) ||
        !isRepublishReason(lastRepublishReason)
    ) {
        return { ok: false, reason: 'bad_url' }
    }
    const ref = parseImageRef(originalRef)
    if (!ref || ref.source !== 'url' || ref.pseudoTeam !== undefined) {
        return { ok: false, reason: 'bad_ref' }
    }
    const canonical = canonicalizeUrl(currentUrl)
    if (!canonical || canonical.fetch !== currentUrl) {
        return { ok: false, reason: 'bad_url' }
    }
    if (canonical.domain !== kafkaKey) {
        return { ok: false, reason: 'foreign_domain' }
    }
    return {
        ok: true,
        candidate: {
            originalRef,
            currentUrl,
            host: canonical.host,
            origin: new URL(currentUrl).origin,
            registrableDomain: canonical.domain,
            remainingHops,
            notBeforeMs,
            firstSeenAtMs,
            fetchCount,
            republishCount,
            lastRepublishReason,
        },
    }
}

export function serializeFrontierRecord(candidates: FetchCandidate[]): Buffer {
    const record: FrontierRecord = {
        v: 2,
        jobs: candidates.map((candidate) => ({
            originalRef: candidate.originalRef,
            currentUrl: candidate.currentUrl,
            remainingHops: candidate.remainingHops,
            notBeforeMs: candidate.notBeforeMs,
            firstSeenAtMs: candidate.firstSeenAtMs,
            fetchCount: candidate.fetchCount,
            republishCount: candidate.republishCount,
            lastRepublishReason: candidate.lastRepublishReason,
        })),
    }
    return Buffer.from(JSON.stringify(record))
}
