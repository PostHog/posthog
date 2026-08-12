import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { FetchCandidate, parseCollectedUrlsRecord } from './collected-urls-record'
import { FetchPass, isTerminal } from './fetch-runner'
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
 * The image fetch lane.
 *
 * It runs every decision up to the point of sending a request: age, dedup against three layers, and
 * the record checks. What survives is counted as `fetchable`, which is the offered request rate that
 * phase 0 measures, and is then either sent or, in dry run, only recorded.
 *
 * A bad record and an unreachable Redis are both handled rather than thrown. This lane shares a
 * partition with every site whose URLs key to it, and a throw here stops the consumer, replays the
 * same batch, and holds that partition against all of them.
 */
export class UrlFetchConsumer {
    private readonly seenRefs: RefDedupCache

    constructor(
        private readonly sightings: SightingStore,
        private readonly options: UrlFetchConsumerOptions,
        /** Absent in dry run. The dry run then has nothing to send with, rather than a flag checked at each URL. */
        private readonly runner?: FetchPass
    ) {
        // These arrive from env, where a typo parses to NaN. A NaN age limit makes every comparison
        // false, which silently disables the shed that lets the lane drop a backlog.
        if (!Number.isFinite(options.maxAgeMs) || options.maxAgeMs <= 0) {
            throw new Error(
                `SESSION_RECORDING_ML_IMAGE_FETCH_MAX_AGE_MS must be a positive number, got ${options.maxAgeMs}`
            )
        }
        if (!options.dryRun && !runner) {
            throw new Error('the image fetch lane needs a fetch runner once dry run is cleared')
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

        const fetchable = await this.removeAlreadySeen(candidates)
        if (fetchable.length > 0) {
            ImageFetchConsumerMetrics.incFetchable(fetchable.length)
        }
        const handled = this.runner ? await this.fetchAll(this.runner, fetchable) : fetchable
        if (handled.length > 0) {
            await this.recordSightings(handled, nowMs)
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
     * Send the requests, and report which URLs this lane is finished with.
     *
     * A URL the budget never sent, or one lost to a timeout, is left out so no sighting is written
     * for it. The next session that refers to it then offers it again. That is the only retry this
     * lane has, because nothing here re-reads a Kafka offset.
     */
    private async fetchAll(runner: FetchPass, candidates: FetchCandidate[]): Promise<FetchCandidate[]> {
        let attempts
        try {
            attempts = await runner.run(candidates)
        } catch (error) {
            // The pass answers with outcomes rather than a throw, so reaching here means a defect.
            // A throw would leave this partition replaying the same batch against the same defect.
            logger.error('🌐', 'ml_image_fetch_pass_failed', { count: candidates.length, error: String(error) })
            return []
        }
        return attempts.filter((attempt) => isTerminal(attempt.outcome)).map((attempt) => attempt.candidate)
    }

    /**
     * The URLs this lane knows nothing about yet.
     *
     * A URL whose read failed is left out rather than treated as new. Treating it as new would
     * fetch it, and a store outage would then turn every batch into the full un-deduped request
     * volume aimed at customer sites, over and over, because our own store is down. Leaving it out
     * costs one delay: the next session that refers to the URL offers it again.
     */
    private async removeAlreadySeen(candidates: FetchCandidate[]): Promise<FetchCandidate[]> {
        if (candidates.length === 0) {
            return []
        }
        const keys = candidates.map((candidate) => sightingKey(candidate.pseudoTeam, candidate.urlHash))
        let result
        try {
            result = await this.sightings.read(keys)
        } catch (error) {
            ImageFetchConsumerMetrics.incStoreError('read', keys.length)
            logger.warn('🌐', 'ml_image_fetch_sighting_read_failed', { count: keys.length, error: String(error) })
            return []
        }
        if (result.failed.size > 0) {
            ImageFetchConsumerMetrics.incStoreError('read', result.failed.size)
        }
        if (result.known.size > 0) {
            ImageFetchConsumerMetrics.incDeduped('store', result.known.size)
        }
        return candidates.filter((_candidate, index) => !result.known.has(index) && !result.failed.has(index))
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
