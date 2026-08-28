import { Message } from 'node-rdkafka'
import pLimit from 'p-limit'

import { logger } from '~/common/utils/logger'

import { FetchCandidate, MAX_HOPS, UrlDropReason, parseCollectedUrlsRecord } from './collected-urls-record'
import { CrawlHistoryItem, CrawlHistoryStore, UrlCrawlHistoryItem, configurationCacheKey } from './crawl-history'
import { mergeDuplicateFetchCandidates } from './fetch-candidate-queue'
import {
    AttemptOutcome,
    DELAY_TOO_LONG,
    FetchAttempt,
    FetchPass,
    HOPS_EXHAUSTED,
    isTransientOutcome,
} from './fetch-runner'
import { FrontierDeadLetterReason, FrontierDeadLetterSink } from './frontier-dead-letter-sink'
import { FrontierPublisher, RepublishBatch } from './frontier-publisher'
import { ImageFetchConsumerMetrics, ImageFetchRequestMetrics } from './metrics'

const ONE_HOUR_MS = 60 * 60 * 1000
const REPUBLISH_DEADLINE_FROM_BATCH_START_MS = 200_000
const DEAD_LETTER_BATCH_BUDGET_MS = 50_000
const DEAD_LETTER_PUBLISH_CONCURRENCY = 8

type RejectedFrontierRecord = {
    message: Message
    reasons: UrlDropReason[]
}

export interface UrlFetchConsumerOptions {
    seenTtlSeconds: number
    dryRun: boolean
}

export class UrlFetchConsumer {
    constructor(
        private readonly crawlHistory: CrawlHistoryStore,
        private readonly publisher: FrontierPublisher,
        private readonly options: UrlFetchConsumerOptions,
        private readonly runner?: FetchPass,
        private readonly deadLetters: FrontierDeadLetterSink | null = null
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
        const republishDeadlineAtMonotonicMs = performance.now() + REPUBLISH_DEADLINE_FROM_BATCH_START_MS
        const drops = new Map<UrlDropReason, number>()
        const rejectedRecords: RejectedFrontierRecord[] = []
        const candidatesByRef = new Map<string, FetchCandidate>()
        let dedupedInBatch = 0
        let originCount = 0
        let registrableDomainCount = 0
        let originCandidateCounts: number[] = []
        let registrableDomainCandidateCounts: number[] = []
        const activeBatchId = ImageFetchConsumerMetrics.startBatch()

        try {
            for (const message of messages) {
                const parsed = this.parse(message)
                if (!parsed.ok) {
                    rejectedRecords.push({ message, reasons: [parsed.reason] })
                    continue
                }
                ImageFetchConsumerMetrics.observeRecord(parsed.urlCount)
                ImageFetchConsumerMetrics.observePartitionRecord(
                    message.partition,
                    parsed.urlCount,
                    parsed.candidates.length
                )
                if (parsed.rejected.length > 0) {
                    rejectedRecords.push({
                        message,
                        reasons: parsed.rejected.map((rejected) => rejected.reason),
                    })
                }
                for (const candidate of parsed.candidates) {
                    const partitionCandidate = { ...candidate, sourcePartitions: [message.partition] }
                    const existing = candidatesByRef.get(partitionCandidate.originalRef)
                    if (existing) {
                        dedupedInBatch += 1
                        candidatesByRef.set(
                            partitionCandidate.originalRef,
                            mergeDuplicateFetchCandidates(existing, partitionCandidate)
                        )
                    } else {
                        candidatesByRef.set(partitionCandidate.originalRef, partitionCandidate)
                    }
                }
            }
            const candidates = [...candidatesByRef.values()]
            candidatesByRef.clear()
            const origins = new Map<string, number>()
            const registrableDomains = new Map<string, number>()
            const partitionOrigins = new Map<number, Map<string, number>>()
            const partitionRegistrableDomains = new Map<number, Map<string, number>>()
            for (const candidate of candidates) {
                ImageFetchConsumerMetrics.observeAge(Math.max(0, nowMs - candidate.firstSeenAtMs) / 1000)
                origins.set(candidate.origin, (origins.get(candidate.origin) ?? 0) + 1)
                registrableDomains.set(
                    candidate.registrableDomain,
                    (registrableDomains.get(candidate.registrableDomain) ?? 0) + 1
                )
                for (const sourcePartition of candidate.sourcePartitions ?? []) {
                    ImageFetchConsumerMetrics.incPartitionUrls(sourcePartition, 'unique', 1)
                    incrementNestedCount(partitionOrigins, sourcePartition, candidate.origin)
                    incrementNestedCount(partitionRegistrableDomains, sourcePartition, candidate.registrableDomain)
                }
            }
            originCount = origins.size
            registrableDomainCount = registrableDomains.size
            originCandidateCounts = [...origins.values()]
            registrableDomainCandidateCounts = [...registrableDomains.values()]
            for (const [partition, partitionOriginCounts] of partitionOrigins) {
                ImageFetchConsumerMetrics.observePartitionBatchDiversity(
                    partition,
                    [...partitionOriginCounts.values()],
                    [...(partitionRegistrableDomains.get(partition)?.values() ?? [])]
                )
            }

            if (this.options.dryRun || candidates.length === 0) {
                await this.parkRejectedRecords(rejectedRecords, drops)
                return
            }

            const keys = [
                ...candidates.map((candidate) => candidate.originalRef),
                ...[...origins.keys()].flatMap((origin) => [
                    configurationCacheKey(origin, 'robots'),
                    configurationCacheKey(origin, 'tdmrep'),
                ]),
            ]
            const stored = await this.runCrawlHistoryOperation('read', keys.length, () => this.crawlHistory.read(keys))

            const fetchable: FetchCandidate[] = []
            const notReady: FetchCandidate[] = []
            for (const candidate of candidates) {
                const history = stored.get(candidate.originalRef)
                if (history?.kind === 'url' && history.nextFetchAtMs > nowMs) {
                    ImageFetchConsumerMetrics.incDeduped('store', 1)
                    for (const sourcePartition of candidate.sourcePartitions ?? []) {
                        ImageFetchConsumerMetrics.incPartitionUrls(sourcePartition, 'store_deduped', 1)
                    }
                    continue
                }
                if (candidate.notBeforeMs > nowMs) {
                    notReady.push(candidate)
                    for (const sourcePartition of candidate.sourcePartitions ?? []) {
                        ImageFetchConsumerMetrics.incPartitionUrls(sourcePartition, 'not_ready', 1)
                    }
                } else {
                    fetchable.push(candidate)
                    for (const sourcePartition of candidate.sourcePartitions ?? []) {
                        ImageFetchConsumerMetrics.incPartitionUrls(sourcePartition, 'fetchable', 1)
                    }
                }
            }
            ImageFetchConsumerMetrics.incFetchable(fetchable.length)

            const republishBatch = this.publisher.createRepublishBatch(republishDeadlineAtMonotonicMs)
            const attempts = await this.runner!.run(fetchable, stored, republishBatch)
            attempts.push(
                ...(await Promise.all(
                    notReady.map((candidate) => this.republishNotReady(republishBatch, candidate, nowMs))
                ))
            )
            const updates: CrawlHistoryItem[] = []
            for (const attempt of attempts) {
                updates.push(...attempt.configurationUpdates)
                if (attempt.history) {
                    updates.push(attempt.history)
                }
            }
            if (updates.length > 0) {
                await this.runCrawlHistoryOperation('write', updates.length, () => this.crawlHistory.write(updates))
            }
            const republishResult = await republishBatch.flush()
            const lost = attempts.filter((attempt) => attempt.lost).length + republishResult.failedUrls
            if (lost > 0) {
                throw new Error(`the image fetch lane could not account for ${lost} URLs`)
            }
            for (const attempt of attempts) {
                for (const sourcePartition of attempt.candidate.sourcePartitions ?? []) {
                    ImageFetchRequestMetrics.incPartitionAttempt(
                        sourcePartition,
                        attempt.finished ? 'completed' : 'republished',
                        attempt.outcome
                    )
                }
                if (!attempt.finished && isTransientOutcome(attempt.outcome)) {
                    ImageFetchRequestMetrics.incRetryCause(attempt.outcome)
                }
            }
            await this.parkRejectedRecords(rejectedRecords, drops)
        } finally {
            ImageFetchConsumerMetrics.finishBatch(activeBatchId)
            this.recordMetrics(
                drops,
                dedupedInBatch,
                originCount,
                registrableDomainCount,
                originCandidateCounts,
                registrableDomainCandidateCounts,
                startedAt
            )
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

    private async parkRejectedRecords(
        records: RejectedFrontierRecord[],
        drops: Map<UrlDropReason, number>
    ): Promise<void> {
        const deadlineAtMonotonicMs = performance.now() + DEAD_LETTER_BATCH_BUDGET_MS
        const limit = pLimit(DEAD_LETTER_PUBLISH_CONCURRENCY)
        let firstFailure: unknown
        const outcomes = await Promise.allSettled(
            records.map(({ message, reasons }) =>
                limit(async () => {
                    if (firstFailure) {
                        throw firstFailure
                    }
                    try {
                        await this.parkRejectedRecord(message, reasons, deadlineAtMonotonicMs)
                    } catch (error) {
                        firstFailure = error
                        throw error
                    }
                })
            )
        )
        for (const outcome of outcomes) {
            if (outcome.status === 'rejected') {
                throw outcome.reason
            }
        }
        for (const { reasons } of records) {
            for (const reason of reasons) {
                drops.set(reason, (drops.get(reason) ?? 0) + 1)
            }
        }
    }

    private async parkRejectedRecord(
        message: Message,
        reasons: UrlDropReason[],
        deadlineAtMonotonicMs: number
    ): Promise<void> {
        if (!this.deadLetters) {
            return
        }
        const reason = this.deadLetterReason(reasons)
        const remainingMs = deadlineAtMonotonicMs - performance.now()
        if (remainingMs <= 0) {
            const error = new Error('image-fetch dead-letter batch exceeded its publish budget')
            ImageFetchConsumerMetrics.incDeadLetterFailed(reason)
            logger.error('🌐', 'ml_image_fetch_dead_letter_publish_failed', { reason, error: error.name })
            throw error
        }
        let timeout: NodeJS.Timeout | undefined
        try {
            await Promise.race([
                this.deadLetters.park(message, reason),
                new Promise<never>((_, reject) => {
                    timeout = setTimeout(
                        () => reject(new Error('image-fetch dead-letter batch exceeded its publish budget')),
                        remainingMs
                    )
                }),
            ])
        } catch (error) {
            ImageFetchConsumerMetrics.incDeadLetterFailed(reason)
            logger.error('🌐', 'ml_image_fetch_dead_letter_publish_failed', {
                reason,
                error: error instanceof Error ? error.name : 'unknown',
            })
            throw error
        } finally {
            if (timeout) {
                clearTimeout(timeout)
            }
        }
        ImageFetchConsumerMetrics.incDeadLettered(reason)
    }

    private deadLetterReason(reasons: UrlDropReason[]): FrontierDeadLetterReason {
        const distinctReasons = new Set(reasons)
        return distinctReasons.size === 1 ? reasons[0] : 'multiple'
    }

    private async runCrawlHistoryOperation<T>(
        operation: 'read' | 'write',
        affectedKeys: number,
        run: () => Promise<T>
    ): Promise<T> {
        const startedAt = process.hrtime.bigint()
        let outcome: 'success' | 'error' = 'success'
        try {
            return await run()
        } catch (error) {
            outcome = 'error'
            ImageFetchConsumerMetrics.incStoreError(operation, affectedKeys)
            throw error
        } finally {
            ImageFetchConsumerMetrics.observeStoreDuration(
                operation,
                outcome,
                Number(process.hrtime.bigint() - startedAt) / 1e9
            )
        }
    }

    private async republishNotReady(
        republishBatch: RepublishBatch,
        candidate: FetchCandidate,
        nowMs: number
    ): Promise<FetchAttempt> {
        if (candidate.remainingHops === 0) {
            return this.terminalAttempt(candidate, HOPS_EXHAUSTED, nowMs)
        }
        const waitMs = candidate.notBeforeMs - nowMs
        const result = await republishBatch.republish(
            candidate,
            {
                currentUrl: candidate.currentUrl,
                host: candidate.host,
                origin: candidate.origin,
                registrableDomain: candidate.registrableDomain,
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
            lost: false,
            configurationUpdates: [],
        }
    }

    private terminalAttempt(candidate: FetchCandidate, outcome: AttemptOutcome, nowMs: number): FetchAttempt {
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

    private terminalHistory(candidate: FetchCandidate, outcome: AttemptOutcome, nowMs: number): UrlCrawlHistoryItem {
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
        registrableDomains: number,
        originCandidateCounts: number[],
        registrableDomainCandidateCounts: number[],
        startedAt: bigint
    ): void {
        if (dedupedInBatch > 0) {
            ImageFetchConsumerMetrics.incDeduped('batch', dedupedInBatch)
        }
        for (const [reason, count] of drops) {
            ImageFetchConsumerMetrics.incDropped(reason, count)
        }
        ImageFetchConsumerMetrics.observeBatchDiversity(originCandidateCounts, registrableDomainCandidateCounts)
        ImageFetchConsumerMetrics.observeBatch(
            origins,
            registrableDomains,
            Number(process.hrtime.bigint() - startedAt) / 1e9
        )
    }
}

function incrementNestedCount(counts: Map<number, Map<string, number>>, partition: number, key: string): void {
    let partitionCounts = counts.get(partition)
    if (!partitionCounts) {
        partitionCounts = new Map<string, number>()
        counts.set(partition, partitionCounts)
    }
    partitionCounts.set(key, (partitionCounts.get(key) ?? 0) + 1)
}
