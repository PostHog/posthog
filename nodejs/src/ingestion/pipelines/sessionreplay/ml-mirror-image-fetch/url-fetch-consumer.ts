import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { FetchCandidate, parseCollectedUrlsRecord } from './collected-urls-record'
import { CRAWL_HISTORY_TTL_SECONDS, CrawlHistoryStore, crawlHistoryKey } from './crawl-history'
import { FetchPass } from './fetch-runner'
import { ImageFetchConsumerMetrics, ImageFetchTeamMetrics, UrlDropReason } from './metrics'
import { TeamVolume } from './team-volume'

export interface UrlFetchConsumerOptions {
    /** A URL older than this is dropped rather than fetched, so a backlog sheds work instead of downloading stale work. */
    maxAgeMs: number
    dedupMaxRefs: number
    /** While true no request leaves this process. Everything else, including the crawl history write, still runs. */
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
    /** Bounded on purpose: one series per busy team, one for the rest, one estimate. Requirement 31. */
    private readonly teamVolume = new TeamVolume()

    constructor(
        private readonly crawlHistory: CrawlHistoryStore,
        private readonly options: UrlFetchConsumerOptions,
        /** Absent in dry run, which is why the dry run sends nothing. No flag is read per URL. */
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
        ImageFetchTeamMetrics.track(this.teamVolume)
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
                if (candidate.notBeforeMs > nowMs) {
                    // Requirement 15. It arrived before its delay tier's period elapsed, which
                    // happens when a wait was longer than the longest tier. Left unrecorded, so the
                    // tier it is still travelling through brings it back.
                    countDrop('too_early')
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
                this.teamVolume.record(candidate.pseudoTeam)
                candidates.push(candidate)
            }
        }

        const fetchable = await this.removeAlreadySeen(candidates)
        if (fetchable.length > 0) {
            ImageFetchConsumerMetrics.incFetchable(fetchable.length)
        }
        const pass = this.runner ? await this.fetchAll(this.runner, fetchable) : { finished: fetchable, lost: 0 }
        if (pass.finished.length > 0) {
            await this.recordFetched(pass.finished, nowMs)
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

        if (pass.lost > 0) {
            // Thrown last, so the counts above are published first. The consumer stores offsets only
            // after this returns, so throwing replays the batch on the pod that takes the partition
            // next. Requirement 21.
            //
            // The replay costs little: the URLs already fetched carry a crawl history entry now, and
            // the read at the top of the batch removes them. A URL is a duplicate at worst, which
            // requirement 22 allows, and the alternative is losing it.
            throw new Error(`the image fetch lane could not republish ${pass.lost} URLs`)
        }
    }

    /**
     * Send the requests. Report the URLs this lane is finished with, and how many it could not put back.
     *
     * A URL left out of `finished` and not counted in `lost` is on its way back through Kafka, so
     * nothing here has to hold it.
     */
    private async fetchAll(
        runner: FetchPass,
        candidates: FetchCandidate[]
    ): Promise<{ finished: FetchCandidate[]; lost: number }> {
        let attempts
        try {
            attempts = await runner.run(candidates)
        } catch (error) {
            // The pass answers with outcomes rather than a throw, so reaching here means a defect.
            // A throw would leave this partition replaying the same batch against the same defect.
            // The name only. An error raised inside the pass can carry a URL in its message.
            logger.error('🌐', 'ml_image_fetch_pass_failed', {
                count: candidates.length,
                error: error instanceof Error ? error.name : 'unknown',
            })
            // Committed rather than replayed, unlike a failed republish. A defect here is the same
            // on every read, so replaying it would stop the partition rather than recover it.
            return { finished: [], lost: 0 }
        }
        return {
            finished: attempts.filter((attempt) => attempt.finished).map((attempt) => attempt.candidate),
            lost: attempts.filter((attempt) => attempt.lost).length,
        }
    }

    /**
     * The URLs this lane knows nothing about yet.
     *
     * A URL whose read failed is left out rather than treated as new.
     *
     * Treating it as new would fetch it. A store outage would then send the full un-deduped volume
     * at customer sites, in every batch, because our own store is down. Leaving it out costs one
     * delay: the next session that refers to the URL offers it again.
     */
    private async removeAlreadySeen(candidates: FetchCandidate[]): Promise<FetchCandidate[]> {
        if (candidates.length === 0) {
            return []
        }
        const keys = candidates.map((candidate) => crawlHistoryKey(candidate.pseudoTeam, candidate.urlHash))
        let result
        try {
            result = await this.crawlHistory.read(keys)
        } catch (error) {
            ImageFetchConsumerMetrics.incStoreError('read', keys.length)
            logger.warn('🌐', 'ml_image_fetch_crawl_history_read_failed', { count: keys.length, error: String(error) })
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
     * The pod cache is marked only for a URL whose crawl history entry was stored.
     *
     * A URL held only in this pod is invisible to every other pod, and to this one after a restart.
     * Marking it before the write is confirmed would drop it from the measurement, and later from
     * fetching.
     */
    private async recordFetched(candidates: FetchCandidate[], nowMs: number): Promise<void> {
        const keys = candidates.map((candidate) => crawlHistoryKey(candidate.pseudoTeam, candidate.urlHash))
        let failed: Set<number>
        try {
            failed = (await this.crawlHistory.record(keys, nowMs, CRAWL_HISTORY_TTL_SECONDS)).failed
        } catch (error) {
            ImageFetchConsumerMetrics.incStoreError('write', keys.length)
            logger.warn('🌐', 'ml_image_fetch_crawl_history_write_failed', { count: keys.length, error: String(error) })
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
