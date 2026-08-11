import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { FetchCandidate, parseCollectedUrlsRecord } from './collected-urls-record'
import { ImageFetchConsumerMetrics, UrlDropReason } from './metrics'
import { SIGHTING_TTL_SECONDS, SightingStore, sightingKey } from './url-sightings'

export interface UrlFetchConsumerOptions {
    /** A URL older than this is dropped rather than fetched, so a backlog sheds work instead of downloading stale work. */
    maxAgeMs: number
    dedupMaxRefs: number
    /** While true no request leaves this process. Everything else, including the sighting write, still runs. */
    dryRun: boolean
}

/**
 * The dry run of the image fetch lane.
 *
 * It runs every decision the fetcher will make up to the point of sending a request, and stops
 * there. What survives to the end is counted as `fetchable`, which is the offered request rate that
 * phase 0 exists to measure, and recorded so the rate phase 1 sees is the rate after dedup rather
 * than before it.
 *
 * A bad record and an unreachable Redis are both handled rather than thrown. This lane shares a
 * partition with every site whose URLs key to it, and a throw here stops the consumer, replays the
 * same batch, and holds that partition against all of them.
 */
export class UrlFetchConsumer {
    private readonly seenRefs: RefDedupCache

    constructor(
        private readonly sightings: SightingStore,
        private readonly options: UrlFetchConsumerOptions
    ) {
        // These arrive from env, where a typo parses to NaN. A NaN age limit makes every comparison
        // false, which silently disables the shed that lets the lane drop a backlog.
        if (!Number.isFinite(options.maxAgeMs) || options.maxAgeMs <= 0) {
            throw new Error(
                `SESSION_RECORDING_ML_IMAGE_FETCH_MAX_AGE_MS must be a positive number, got ${options.maxAgeMs}`
            )
        }
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
                // After dedup, so the distribution describes the URLs this lane acts on rather than
                // being weighted by how often a popular image reappears.
                ImageFetchConsumerMetrics.observeAge(Math.max(0, nowMs - candidate.capturedAtMs) / 1000)
                candidates.push(candidate)
            }
        }

        const { fetchable, readFailed } = await this.removeAlreadySeen(candidates)
        if (fetchable.length > 0) {
            ImageFetchConsumerMetrics.incFetchable(fetchable.length)
        }
        // A store that just failed a read gets no writes: the un-deduped write volume is the largest
        // this lane ever offers, and sending it to a struggling Redis makes it slower still.
        if (fetchable.length > 0 && !readFailed) {
            await this.recordSightings(fetchable, nowMs)
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
     * A URL whose read failed comes back as fetchable, which overstates the offered rate. That is
     * the safe direction while nothing is being sent, and it is not once requests go out, so the
     * failure is counted rather than only logged.
     */
    private async removeAlreadySeen(
        candidates: FetchCandidate[]
    ): Promise<{ fetchable: FetchCandidate[]; readFailed: boolean }> {
        if (candidates.length === 0) {
            return { fetchable: [], readFailed: false }
        }
        const keys = candidates.map((candidate) => sightingKey(candidate.pseudoTeam, candidate.urlHash))
        let result
        try {
            result = await this.sightings.read(keys)
        } catch (error) {
            ImageFetchConsumerMetrics.incStoreError('read', keys.length)
            logger.warn('🌐', 'ml_image_fetch_sighting_read_failed', { count: keys.length, error: String(error) })
            return { fetchable: candidates, readFailed: true }
        }
        if (result.failed > 0) {
            ImageFetchConsumerMetrics.incStoreError('read', result.failed)
        }
        if (result.known.size > 0) {
            ImageFetchConsumerMetrics.incDeduped('store', result.known.size)
        }
        return {
            fetchable: candidates.filter((_candidate, index) => !result.known.has(index)),
            readFailed: result.failed > 0,
        }
    }

    /**
     * The pod cache is marked only for a URL whose sighting was stored. A URL held locally but
     * absent from the shared store is invisible to every other pod and to this one after a restart,
     * so marking it before the write is confirmed would drop it from the measurement and, later,
     * from fetching.
     */
    private async recordSightings(candidates: FetchCandidate[], nowMs: number): Promise<void> {
        const keys = candidates.map((candidate) => sightingKey(candidate.pseudoTeam, candidate.urlHash))
        let failed: Set<number>
        try {
            failed = (await this.sightings.record(keys, nowMs, SIGHTING_TTL_SECONDS)).failed
        } catch (error) {
            ImageFetchConsumerMetrics.incStoreError('write', keys.length)
            logger.warn('🌐', 'ml_image_fetch_sighting_write_failed', { count: keys.length, error: String(error) })
            return
        }
        if (failed.size > 0) {
            ImageFetchConsumerMetrics.incStoreError('write', failed.size)
        }
        candidates.forEach((candidate, index) => {
            if (!failed.has(index)) {
                this.seenRefs.add(candidate.ref)
            }
        })
    }
}
