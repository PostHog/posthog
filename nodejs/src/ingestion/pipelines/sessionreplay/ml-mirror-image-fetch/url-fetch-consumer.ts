import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'

import { FetchCandidate, MAX_HOPS, parseCollectedUrlsRecord } from './collected-urls-record'
import { CrawlHistoryItem, CrawlHistoryStore, UrlCrawlHistoryItem, configurationCacheKey } from './crawl-history'
import { DELAY_TOO_LONG, FetchAttempt, FetchPass, HOPS_EXHAUSTED } from './fetch-runner'
import { FrontierPublisher } from './frontier-publisher'
import { ImageFetchConsumerMetrics, ImageFetchRequestMetrics, UrlDropReason } from './metrics'

const ONE_HOUR_MS = 60 * 60 * 1000

export interface UrlFetchConsumerOptions {
    seenTtlSeconds: number
    dryRun: boolean
}

export class UrlFetchConsumer {
    constructor(
        private readonly crawlHistory: CrawlHistoryStore,
        private readonly publisher: FrontierPublisher,
        private readonly options: UrlFetchConsumerOptions,
        private readonly runner?: FetchPass
    ) {
        if (!Number.isInteger(options.seenTtlSeconds) || options.seenTtlSeconds < 60 * 60) {
            throw new Error('AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS must be at least 3600')
        }
        if (!options.dryRun && !runner) {
            throw new Error('the image fetch lane needs a fetch runner once dry run is cleared')
        }
        ImageFetchConsumerMetrics.setDryRun(options.dryRun)
    }

    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        const startedAt = process.hrtime.bigint()
        const drops = new Map<UrlDropReason, number>()
        const candidatesByRef = new Map<string, FetchCandidate>()
        let dedupedInBatch = 0

        for (const message of messages) {
            const parsed = this.parse(message)
            if (!parsed.ok) {
                drops.set(parsed.reason, (drops.get(parsed.reason) ?? 0) + 1)
                continue
            }
            ImageFetchConsumerMetrics.observeRecord(parsed.urlCount)
            for (const rejected of parsed.rejected) {
                drops.set(rejected.reason, (drops.get(rejected.reason) ?? 0) + 1)
            }
            for (const candidate of parsed.candidates) {
                const existing = candidatesByRef.get(candidate.originalRef)
                if (existing) {
                    dedupedInBatch += 1
                    candidatesByRef.set(candidate.originalRef, foldDuplicateCandidate(existing, candidate))
                    continue
                }
                ImageFetchConsumerMetrics.observeAge(Math.max(0, nowMs - candidate.firstSeenAtMs) / 1000)
                candidatesByRef.set(candidate.originalRef, candidate)
            }
        }
        const candidates = [...candidatesByRef.values()]
        const origins = new Set(candidates.map((candidate) => candidate.origin))

        if (this.options.dryRun || candidates.length === 0) {
            this.recordMetrics(drops, dedupedInBatch, origins.size, startedAt)
            return
        }

        const keys = [
            ...candidates.map((candidate) => candidate.originalRef),
            ...[...origins].flatMap((origin) => [
                configurationCacheKey(origin, 'robots'),
                configurationCacheKey(origin, 'tdmrep'),
            ]),
        ]
        let stored: Map<string, CrawlHistoryItem>
        try {
            stored = await this.crawlHistory.read(keys)
        } catch (error) {
            ImageFetchConsumerMetrics.incStoreError('read', keys.length)
            throw error
        }

        const fetchable: FetchCandidate[] = []
        const notReady: FetchCandidate[] = []
        for (const candidate of candidates) {
            const history = stored.get(candidate.originalRef)
            if (history?.kind === 'url' && history.nextFetchAtMs > nowMs) {
                ImageFetchConsumerMetrics.incDeduped('store', 1)
                continue
            }
            if (candidate.notBeforeMs > nowMs) {
                notReady.push(candidate)
            } else {
                fetchable.push(candidate)
            }
        }
        ImageFetchConsumerMetrics.incFetchable(fetchable.length)

        const attempts = await this.runner!.run(fetchable, stored)
        attempts.push(...(await Promise.all(notReady.map((candidate) => this.republishNotReady(candidate, nowMs)))))
        const updates: CrawlHistoryItem[] = []
        for (const attempt of attempts) {
            updates.push(...attempt.configurationUpdates)
            if (attempt.history) {
                updates.push(attempt.history)
            }
        }
        if (updates.length > 0) {
            try {
                await this.crawlHistory.write(updates)
            } catch (error) {
                ImageFetchConsumerMetrics.incStoreError('write', updates.length)
                throw error
            }
        }
        const lost = attempts.filter((attempt) => attempt.lost).length
        this.recordMetrics(drops, dedupedInBatch, origins.size, startedAt)
        if (lost > 0) {
            throw new Error(`the image fetch lane could not account for ${lost} URLs`)
        }
    }

    private parse(message: Message): ReturnType<typeof parseCollectedUrlsRecord> {
        try {
            return parseCollectedUrlsRecord(message.value, message.key?.toString() ?? null)
        } catch (error) {
            logger.error('🌐', 'ml_image_fetch_record_parse_threw', {
                error: error instanceof Error ? error.name : 'unknown',
            })
            return { ok: false, reason: 'malformed' }
        }
    }

    private async republishNotReady(candidate: FetchCandidate, nowMs: number): Promise<FetchAttempt> {
        if (candidate.remainingHops === 0) {
            return this.terminalAttempt(candidate, HOPS_EXHAUSTED, nowMs)
        }
        const waitMs = candidate.notBeforeMs - nowMs
        const result = await this.publisher.republish(
            candidate,
            {
                currentUrl: candidate.currentUrl,
                host: candidate.host,
                origin: candidate.origin,
                domain: candidate.domain,
            },
            'not_ready',
            waitMs
        )
        if (result === 'refused_delay' || waitMs > ONE_HOUR_MS) {
            return this.terminalAttempt(candidate, DELAY_TOO_LONG, nowMs)
        }
        return {
            candidate,
            outcome: 'backoff',
            finished: false,
            lost: result === 'failed',
            configurationUpdates: [],
        }
    }

    private terminalAttempt(candidate: FetchCandidate, outcome: string, nowMs: number): FetchAttempt {
        ImageFetchRequestMetrics.observeCompletedUrl(
            outcome,
            'none',
            Math.max(0, nowMs - candidate.firstSeenAtMs) / 1000,
            candidate.fetchCount,
            candidate.republishCount
        )
        ImageFetchRequestMetrics.observeHops(MAX_HOPS - candidate.remainingHops)
        return {
            candidate,
            outcome,
            finished: true,
            lost: false,
            history: this.terminalHistory(candidate, outcome, nowMs),
            configurationUpdates: [],
        }
    }

    private terminalHistory(candidate: FetchCandidate, outcome: string, nowMs: number): UrlCrawlHistoryItem {
        const nextFetchAtMs = nowMs + this.options.seenTtlSeconds * 1000
        return {
            kind: 'url',
            key: candidate.originalRef,
            nextFetchAtMs,
            storageExpiresAtMs: nextFetchAtMs,
            outcome,
        }
    }

    private recordMetrics(
        drops: Map<UrlDropReason, number>,
        dedupedInBatch: number,
        origins: number,
        startedAt: bigint
    ): void {
        if (dedupedInBatch > 0) {
            ImageFetchConsumerMetrics.incDeduped('batch', dedupedInBatch)
        }
        for (const [reason, count] of drops) {
            ImageFetchConsumerMetrics.incDropped(reason, count)
        }
        ImageFetchConsumerMetrics.observeBatch(origins, Number(process.hrtime.bigint() - startedAt) / 1e9)
    }
}

function foldDuplicateCandidate(left: FetchCandidate, right: FetchCandidate): FetchCandidate {
    let preferredRoute = left
    if (
        right.remainingHops < left.remainingHops ||
        (right.remainingHops === left.remainingHops && right.republishCount > left.republishCount) ||
        (right.remainingHops === left.remainingHops &&
            right.republishCount === left.republishCount &&
            right.fetchCount > left.fetchCount)
    ) {
        preferredRoute = right
    }
    const latestState = left.republishCount >= right.republishCount ? left : right
    return {
        ...preferredRoute,
        remainingHops: Math.min(left.remainingHops, right.remainingHops),
        notBeforeMs: Math.max(left.notBeforeMs, right.notBeforeMs),
        firstSeenAtMs: Math.min(left.firstSeenAtMs, right.firstSeenAtMs),
        fetchCount: Math.max(left.fetchCount, right.fetchCount),
        republishCount: Math.max(left.republishCount, right.republishCount),
        lastRepublishReason: latestState.lastRepublishReason,
    }
}
