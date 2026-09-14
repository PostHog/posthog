import type { UrlPolicyDecline } from '@posthog/replay-anonymizer'

import { parseJSON } from '~/common/utils/json-parse'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { ImageFetchBlockReason, isImageFetchBlockReason } from './block-reason'
import { tryCanonicalizeUrl } from './politeness-key'

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
/** Why the parser dropped a job on its own, without rejecting the record that carries it. */
export type UrlSkipReason = UrlPolicyDecline
export type StoredRepublishReason =
    | 'redirect'
    | 'retry'
    | 'not_ready'
    | 'pass_deadline'
    | 'origin_map_full'
    | 'registrable_domain_map_full'
export type RepublishReason = StoredRepublishReason

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
    lastRepublishReason: StoredRepublishReason | null
    lastBlockReason?: ImageFetchBlockReason
    sourcePartitions?: readonly number[]
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
            | 'lastBlockReason'
        >
    >
}

export type RecordParse =
    | {
          ok: true
          candidates: FetchCandidate[]
          urlCount: number
          rejected: { reason: UrlDropReason }[]
          skipped: { reason: UrlSkipReason }[]
      }
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

function isStoredRepublishReason(value: unknown): value is StoredRepublishReason | null {
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
    const skipped: { reason: UrlSkipReason }[] = []
    for (const job of parsed.jobs) {
        const parsedJob = parseJob(job, key)
        if (parsedJob.kind === 'rejected') {
            return { ok: false, reason: parsedJob.reason }
        }
        if (parsedJob.kind === 'skipped') {
            skipped.push({ reason: parsedJob.reason })
            continue
        }
        candidates.push(parsedJob.candidate)
    }
    return { ok: true, candidates, urlCount: parsed.jobs.length, rejected, skipped }
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
    const skipped: { reason: UrlSkipReason }[] = []
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
        const verdict = tryCanonicalizeUrl(entry.url)
        if (!verdict.ok) {
            if (verdict.unwanted) {
                skipped.push({ reason: verdict.decline })
            } else {
                rejected.push({ reason: 'bad_url' })
            }
            continue
        }
        const canonical = verdict.url
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
    return { ok: true, candidates, urlCount: urls.length, rejected, skipped }
}

type ParsedJob =
    | { kind: 'candidate'; candidate: FetchCandidate }
    | { kind: 'rejected'; reason: Extract<UrlDropReason, 'bad_ref' | 'bad_url' | 'foreign_domain'> }
    | { kind: 'skipped'; reason: UrlSkipReason }

function parseJob(job: unknown, kafkaKey: string): ParsedJob {
    if (!isRecord(job)) {
        return { kind: 'rejected', reason: 'bad_url' }
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
        lastBlockReason,
        lowOriginDiversityDeferred,
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
        !isStoredRepublishReason(lastRepublishReason) ||
        (lastBlockReason !== undefined && !isImageFetchBlockReason(lastBlockReason)) ||
        (lowOriginDiversityDeferred !== undefined && typeof lowOriginDiversityDeferred !== 'boolean')
    ) {
        return { kind: 'rejected', reason: 'bad_url' }
    }
    const ref = parseImageRef(originalRef)
    if (!ref || ref.source !== 'url' || ref.pseudoTeam !== undefined) {
        return { kind: 'rejected', reason: 'bad_ref' }
    }
    const verdict = tryCanonicalizeUrl(currentUrl)
    if (!verdict.ok) {
        // A rejected job sends its whole record to the dead-letter topic, and a record can hold an
        // unwanted URL next to real images, so an unwanted URL is skipped on its own instead.
        return verdict.unwanted ? { kind: 'skipped', reason: verdict.decline } : { kind: 'rejected', reason: 'bad_url' }
    }
    const canonical = verdict.url
    if (canonical.fetch !== currentUrl) {
        return { kind: 'rejected', reason: 'bad_url' }
    }
    if (canonical.domain !== kafkaKey) {
        return { kind: 'rejected', reason: 'foreign_domain' }
    }
    return {
        kind: 'candidate',
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
            lastBlockReason,
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
            lastBlockReason: candidate.lastBlockReason,
        })),
    }
    return Buffer.from(JSON.stringify(record))
}
