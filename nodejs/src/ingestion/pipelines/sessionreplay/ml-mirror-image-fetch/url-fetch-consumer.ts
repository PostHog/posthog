import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { FetchCandidate, MAX_HOPS, parseCollectedUrlsRecord } from './collected-urls-record'
import { CRAWL_HISTORY_TTL_SECONDS, CrawlHistoryStore, crawlHistoryKey } from './crawl-history'
import { FetchPass, HOPS_EXHAUSTED } from './fetch-runner'
import { FrontierPublisher } from './frontier-publisher'
import { ImageFetchConsumerMetrics, ImageFetchRequestMetrics, ImageFetchTeamMetrics, UrlDropReason } from './metrics'
import { TeamVolume } from './team-volume'

export interface UrlFetchConsumerOptions {
    /** The lane drops a URL older than this, so a backlog sheds work instead of fetching stale URLs. */
    maxAgeMs: number
    dedupMaxRefs: number
    /** While true, no request leaves this process. Everything else still runs, including the crawl history write. */
    dryRun: boolean
}

/**
 * The image fetch lane.
 *
 * The consumer handles a bad record and an unreachable Redis instead of throwing. This lane shares a
 * partition with every site whose URLs key to it, and a throw here stops the consumer, replays the
 * same batch, and holds that partition against all of them.
 */
export class UrlFetchConsumer {
    private readonly seenRefs: RefDedupCache
    /** Bounded on purpose: one series for each busy team, one for the rest, one estimate. Requirement 31. */
    private readonly teamVolume = new TeamVolume()

    constructor(
        private readonly crawlHistory: CrawlHistoryStore,
        private readonly publisher: FrontierPublisher,
        private readonly options: UrlFetchConsumerOptions,
        /** Absent in dry run, so the dry run sends nothing. The lane reads no flag for each URL. */
        private readonly runner?: FetchPass
    ) {
        // These arrive from env, where a typo parses to NaN. A NaN age limit makes every comparison
        // false, which disables the shed that lets the lane drop a backlog.
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
        // Wall clock, not the caller's nowMs: nowMs dates the URLs, and a test can set it far from
        // the present, which would make the duration meaningless.
        const startedAt = process.hrtime.bigint()
        const drops = new Map<UrlDropReason, number>()
        const countDrop = (reason: UrlDropReason, count = 1): void => {
            drops.set(reason, (drops.get(reason) ?? 0) + count)
        }

        const domains = new Set<string>()
        const seenInBatch = new Set<string>()
        const candidates: FetchCandidate[] = []
        const notReady: FetchCandidate[] = []
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
                    // A wait longer than the longest tier, so the tier it came out of covered only
                    // part of it. It goes back for the rest and spends a hop. Requirement 15.
                    notReady.push(candidate)
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
                // how often a popular image reappears.
                ImageFetchConsumerMetrics.observeAge(Math.max(0, nowMs - candidate.capturedAtMs) / 1000)
                this.teamVolume.record(candidate.pseudoTeam)
                candidates.push(candidate)
            }
        }

        const known = await this.removeAlreadySeen(candidates)
        if (known.fetchable.length > 0) {
            ImageFetchConsumerMetrics.incFetchable(known.fetchable.length)
        }
        const pass = this.runner
            ? await this.fetchAll(this.runner, known.fetchable)
            : { finished: known.fetchable, lost: 0 }
        const held = await this.rescheduleNotReady(notReady, nowMs)
        const finished = [...pass.finished, ...held.exhausted]
        if (finished.length > 0) {
            await this.recordFetched(finished, nowMs)
        }
        const lost = pass.lost + known.unaccounted + held.lost

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

        if (lost > 0) {
            // Thrown last, so the counts above publish first. The consumer stores offsets only after
            // this returns, so a throw replays the batch on the pod that takes the partition next.
            // Requirement 21.
            //
            // The replay costs little: the URLs already fetched carry a crawl history entry now, and
            // the read at the top of the batch removes them. A URL is a duplicate at worst, which
            // requirement 22 allows, and the alternative is a lost URL.
            throw new Error(`the image fetch lane could not account for ${lost} URLs`)
        }
    }

    /**
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
            // The log holds the error name only, because an error from the pass can carry a URL.
            logger.error('🌐', 'ml_image_fetch_pass_failed', {
                count: candidates.length,
                error: error instanceof Error ? error.name : 'unknown',
            })
            // The batch commits rather than replays, unlike a failed republish. A defect here is the
            // same on every read, so a replay would stop the partition rather than recover it.
            return { finished: [], lost: 0 }
        }
        return {
            finished: attempts.filter((attempt) => attempt.finished).map((attempt) => attempt.candidate),
            lost: attempts.filter((attempt) => attempt.lost).length,
        }
    }

    /**
     * A URL whose read failed is neither fetched nor counted as new. To count it as new would fetch
     * it, and a store outage would then send the full un-deduped volume at customer sites, in every
     * batch, because our own store is down. It counts as unaccounted instead, which holds the batch
     * rather than loses it. Requirement 21.
     */
    private async removeAlreadySeen(
        candidates: FetchCandidate[]
    ): Promise<{ fetchable: FetchCandidate[]; unaccounted: number }> {
        if (candidates.length === 0) {
            return { fetchable: [], unaccounted: 0 }
        }
        const keys = candidates.map((candidate) => crawlHistoryKey(candidate.pseudoTeam, candidate.urlHash))
        let result
        try {
            result = await this.crawlHistory.read(keys)
        } catch (error) {
            ImageFetchConsumerMetrics.incStoreError('read', keys.length)
            logger.warn('🌐', 'ml_image_fetch_crawl_history_read_failed', { count: keys.length, error: String(error) })
            return { fetchable: [], unaccounted: keys.length }
        }
        if (result.failed.size > 0) {
            ImageFetchConsumerMetrics.incStoreError('read', result.failed.size)
        }
        if (result.known.size > 0) {
            ImageFetchConsumerMetrics.incDeduped('store', result.known.size)
        }
        return {
            fetchable: candidates.filter((_candidate, index) => !result.known.has(index) && !result.failed.has(index)),
            unaccounted: result.failed.size,
        }
    }

    /**
     * A URL waiting out a delay has no crawl history entry and no other copy in Kafka, so a drop
     * here loses it until a session refers to the same image again. Requirements 15 and 21.
     *
     * One with no hops left cannot go round again. The lane records it and stops, exactly as the
     * fetch pass does with a URL that runs out mid-chain. Requirements 12 and 24.
     */
    private async rescheduleNotReady(
        candidates: FetchCandidate[],
        nowMs: number
    ): Promise<{ lost: number; exhausted: FetchCandidate[] }> {
        let lost = 0
        const exhausted: FetchCandidate[] = []
        for (const candidate of candidates) {
            if (candidate.hopsRemaining <= 1) {
                ImageFetchRequestMetrics.incOutcome(HOPS_EXHAUSTED)
                ImageFetchRequestMetrics.observeHops(MAX_HOPS)
                exhausted.push(candidate)
                continue
            }
            const target = { url: candidate.url, host: candidate.host, domain: candidate.domain }
            if (!(await this.publisher.republish(candidate, target, 'not_ready', candidate.notBeforeMs - nowMs))) {
                lost++
            }
        }
        return { lost, exhausted }
    }

    /**
     * This marks the pod cache only for a URL whose crawl history entry reached the store.
     *
     * A URL held only in this pod is invisible to every other pod, and to this one after a restart.
     * A mark before the store confirms the write would drop the URL from the measurement, and later
     * from fetching.
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
