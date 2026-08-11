import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { FetchCandidate, parseCollectedUrlsRecord } from './collected-urls-record'
import { ImageFetchConsumerMetrics, UrlDropReason } from './metrics'
import { SEEN_TTL_SECONDS, UrlLedger, ledgerKey } from './url-ledger'

export interface UrlFetchConsumerOptions {
    /** A URL older than this is dropped rather than fetched, so a backlog sheds work instead of downloading stale work. */
    maxAgeMs: number
    dedupMaxRefs: number
    /** While true no request leaves this process. Everything else, including the ledger write, still runs. */
    dryRun: boolean
}

/**
 * The dry run of the image fetch lane.
 *
 * It runs every decision the fetcher will make up to the point of sending a request, and stops
 * there. What survives to the end is counted as `fetchable`, which is the offered request rate that
 * phase 0 exists to measure, and written to the ledger so the rate that phase 1 sees is the rate
 * after dedup rather than before it.
 *
 * Nothing here throws on a bad record or an unreachable Redis. This lane shares a partition with
 * every site whose URLs key to it, so one unparseable record or one Redis blip must not hold that
 * partition.
 */
export class UrlFetchConsumer {
    private readonly seenRefs: RefDedupCache

    constructor(
        private readonly ledger: UrlLedger,
        private readonly options: UrlFetchConsumerOptions
    ) {
        this.seenRefs = new RefDedupCache('image_fetch_consumer', options.dedupMaxRefs)
        ImageFetchConsumerMetrics.setDryRun(options.dryRun)
    }

    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        // Wall clock, not the caller's nowMs: nowMs dates the URLs and a test is free to set it far
        // from the present, which would make the duration meaningless.
        const startedAt = process.hrtime.bigint()
        const drops = new Map<UrlDropReason, number>()
        const countDrop = (reason: UrlDropReason, count = 1): void => {
            drops.set(reason, (drops.get(reason) ?? 0) + count)
        }

        const domains = new Set<string>()
        const seenInBatch = new Set<string>()
        const candidates: FetchCandidate[] = []
        let dedupedInBatch = 0
        let dedupedInPod = 0

        for (const message of messages) {
            const parsed = parseCollectedUrlsRecord(message.value, message.key?.toString() ?? null)
            if (!parsed.ok) {
                countDrop(parsed.reason)
                continue
            }
            ImageFetchConsumerMetrics.observeRecord(parsed.urlCount)
            for (const { reason } of parsed.rejected) {
                countDrop(reason)
            }
            for (const candidate of parsed.candidates) {
                domains.add(candidate.domain)
                ImageFetchConsumerMetrics.observeAge(Math.max(0, nowMs - candidate.capturedAtMs) / 1000)
                if (nowMs - candidate.capturedAtMs > this.options.maxAgeMs) {
                    countDrop('stale')
                    continue
                }
                if (seenInBatch.has(candidate.ref)) {
                    dedupedInBatch++
                    continue
                }
                seenInBatch.add(candidate.ref)
                if (this.seenRefs.has(candidate.ref)) {
                    dedupedInPod++
                    continue
                }
                candidates.push(candidate)
            }
        }

        const fetchable = await this.removeKnownToLedger(candidates)
        for (const candidate of candidates) {
            this.seenRefs.add(candidate.ref)
        }
        if (fetchable.length > 0) {
            ImageFetchConsumerMetrics.incFetchable(fetchable.length)
            await this.recordSeen(fetchable, nowMs)
        }

        if (dedupedInBatch > 0) {
            ImageFetchConsumerMetrics.incDeduped('batch', dedupedInBatch)
        }
        if (dedupedInPod > 0) {
            ImageFetchConsumerMetrics.incDeduped('pod', dedupedInPod)
        }
        for (const [reason, count] of drops) {
            ImageFetchConsumerMetrics.incDropped(reason, count)
        }
        ImageFetchConsumerMetrics.observeBatch(domains.size, Number(process.hrtime.bigint() - startedAt) / 1e9)
    }

    /**
     * A read failure returns every candidate as new. The lane then counts a duplicate as fetchable,
     * which overstates the offered rate, and that is the safe direction to be wrong in while nothing
     * is being sent. Once requests go out it is not, so the failure is counted rather than logged
     * only.
     */
    private async removeKnownToLedger(candidates: FetchCandidate[]): Promise<FetchCandidate[]> {
        if (candidates.length === 0) {
            return []
        }
        const keys = candidates.map((candidate) => ledgerKey(candidate.pseudoTeam, candidate.urlHash))
        let entries
        try {
            entries = await this.ledger.getMany(keys)
        } catch (error) {
            ImageFetchConsumerMetrics.incLedgerError('read')
            logger.warn('🌐', 'ml_image_fetch_ledger_read_failed', { count: keys.length, error: String(error) })
            return candidates
        }
        const fetchable: FetchCandidate[] = []
        let known = 0
        for (const [index, candidate] of candidates.entries()) {
            if (entries[index]) {
                known++
                continue
            }
            fetchable.push(candidate)
        }
        if (known > 0) {
            ImageFetchConsumerMetrics.incDeduped('ledger', known)
        }
        return fetchable
    }

    private async recordSeen(candidates: FetchCandidate[], nowMs: number): Promise<void> {
        try {
            await this.ledger.recordMany(
                candidates.map((candidate) => ({
                    key: ledgerKey(candidate.pseudoTeam, candidate.urlHash),
                    entry: { fetchedAtMs: nowMs, outcome: 'seen' as const },
                    ttlSeconds: SEEN_TTL_SECONDS,
                }))
            )
        } catch (error) {
            ImageFetchConsumerMetrics.incLedgerError('write')
            logger.warn('🌐', 'ml_image_fetch_ledger_write_failed', {
                count: candidates.length,
                error: String(error),
            })
        }
    }
}
