import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { logger } from '~/common/utils/logger'
import { CAPTURE_TIMESTAMP_HEADER } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/image-transport'

import {
    FetchCandidate,
    MAX_JOBS_PER_RECORD,
    MAX_RECORD_BYTES,
    RepublishReason,
    serializeFrontierRecord,
} from './collected-urls-record'
import type { ImageFetchResult } from './image-fetcher'
import { ImageFetchRequestMetrics, RepublishTopic } from './metrics'

export interface DelayTier {
    topic: string
    delayMs: number
    metricTopic: Exclude<RepublishTopic, 'frontier'>
}

export interface FrontierPublisherOptions {
    frontierTopic: string
    scrubTopic: string
    delayTiers: DelayTier[]
    maxConcurrentImagePublishes: number
    maxConcurrentRepublishes: number
}

export type RepublishResult = 'queued' | 'refused_delay'

export interface RepublishFlushResult {
    failedUrls: number
}

interface RepublishDestination {
    topic: string
    metricTopic: RepublishTopic
    delayMs: number
}

interface PendingRepublish {
    candidate: FetchCandidate
    reason: RepublishReason
    destination: RepublishDestination
}

interface PlannedRepublishMessage {
    topic: string
    metricTopic: RepublishTopic
    registrableDomain: string
    candidates: FetchCandidate[]
    reasons: RepublishReason[]
}

interface RepublishDeliveryState {
    failed: boolean
    deadlineExceeded: boolean
}

type RepublishDeliveryResult = 'published' | 'failed' | 'skipped'

const EMPTY_FRONTIER_RECORD_BYTES = serializeFrontierRecord([]).length

export interface RepublishBatch {
    republish(
        candidate: FetchCandidate,
        target: Pick<FetchCandidate, 'currentUrl' | 'host' | 'origin' | 'registrableDomain'>,
        reason: RepublishReason,
        waitMs?: number
    ): Promise<RepublishResult>
    flush(): Promise<RepublishFlushResult>
}

export class FrontierPublisher {
    private readonly delayTiers: DelayTier[]
    private readonly imagePublishes: ConcurrencyController
    private readonly republishes: ConcurrencyController

    constructor(
        private readonly producer: KafkaProducerWrapper,
        private readonly options: FrontierPublisherOptions
    ) {
        this.delayTiers = [...options.delayTiers].sort((left, right) => left.delayMs - right.delayMs)
        if (this.delayTiers.length === 0) {
            throw new Error('the image fetch lane needs at least one delay tier')
        }
        if (!Number.isInteger(options.maxConcurrentImagePublishes) || options.maxConcurrentImagePublishes < 1) {
            throw new Error('the image fetch lane needs a positive image publish limit')
        }
        if (!Number.isInteger(options.maxConcurrentRepublishes) || options.maxConcurrentRepublishes < 1) {
            throw new Error('the image fetch lane needs a positive republish limit')
        }
        this.imagePublishes = new ConcurrencyController(options.maxConcurrentImagePublishes)
        this.republishes = new ConcurrencyController(options.maxConcurrentRepublishes)
    }

    public createRepublishBatch(deadlineAtMonotonicMs = Number.POSITIVE_INFINITY): RepublishBatch {
        return new BufferedRepublishBatch(
            this.producer,
            this.options.frontierTopic,
            this.delayTiers,
            this.republishes,
            deadlineAtMonotonicMs
        )
    }

    public async publishImage(candidate: FetchCandidate, result: ImageFetchResult): Promise<void> {
        if (!result.bytes || !result.contentType) {
            throw new Error('an image publish needs response bytes and a content type')
        }
        const bytes = result.bytes
        const headers: Record<string, string> = {
            'content-type': result.contentType,
            [CAPTURE_TIMESTAMP_HEADER]: String(candidate.firstSeenAtMs),
        }
        if (result.contentEncoding) {
            headers['content-encoding'] = result.contentEncoding
        }
        await this.imagePublishes.run({
            debugTag: candidate.registrableDomain,
            fn: () =>
                this.producer.produce({
                    topic: this.options.scrubTopic,
                    key: Buffer.from(candidate.originalRef),
                    value: bytes,
                    headers,
                }),
        })
    }
}

class BufferedRepublishBatch implements RepublishBatch {
    private readonly pending: PendingRepublish[] = []
    private flushed = false

    constructor(
        private readonly producer: KafkaProducerWrapper,
        private readonly frontierTopic: string,
        private readonly delayTiers: DelayTier[],
        private readonly republishes: ConcurrencyController,
        private readonly deadlineAtMonotonicMs: number
    ) {}

    public republish(
        candidate: FetchCandidate,
        target: Pick<FetchCandidate, 'currentUrl' | 'host' | 'origin' | 'registrableDomain'>,
        reason: RepublishReason,
        waitMs = 0
    ): Promise<RepublishResult> {
        if (this.flushed) {
            return Promise.reject(new Error('an image fetch republish batch cannot accept work after its flush'))
        }
        const spendsHop = reason === 'redirect' || reason === 'retry'
        const remainingHops = candidate.remainingHops - (spendsHop ? 1 : 0)
        if (remainingHops <= 0) {
            return Promise.resolve('refused_delay')
        }

        const effectiveWaitMs = reason === 'retry' ? Math.max(waitMs, this.delayTiers[0].delayMs) : waitMs
        const destination = this.destination(effectiveWaitMs)
        if (!destination) {
            return Promise.resolve('refused_delay')
        }
        this.pending.push({
            candidate: {
                ...candidate,
                ...target,
                remainingHops,
                notBeforeMs: destination.delayMs > 0 ? Date.now() + destination.delayMs : 0,
                republishCount: candidate.republishCount + 1,
                lastRepublishReason: reason,
            },
            reason,
            destination,
        })
        return Promise.resolve('queued')
    }

    public async flush(): Promise<RepublishFlushResult> {
        if (this.flushed) {
            throw new Error('an image fetch republish batch cannot flush more than once')
        }
        this.flushed = true
        if (this.pending.length === 0) {
            return { failedUrls: 0 }
        }
        const startedAt = process.hrtime.bigint()
        try {
            const plans = this.planMessages()
            const deliveryState: RepublishDeliveryState = { failed: false, deadlineExceeded: false }
            const plansByTopic = new Map<RepublishTopic, PlannedRepublishMessage[]>()
            for (const plan of plans) {
                const topicPlans = plansByTopic.get(plan.metricTopic)
                if (topicPlans) {
                    topicPlans.push(plan)
                } else {
                    plansByTopic.set(plan.metricTopic, [plan])
                }
            }
            const topicResults = await Promise.all(
                [...plansByTopic.entries()].map(([metricTopic, topicPlans]) =>
                    this.publishTopic(metricTopic, topicPlans, deliveryState)
                )
            )
            if (deliveryState.deadlineExceeded) {
                ImageFetchRequestMetrics.incRepublishFlushDeadlineExceeded()
            }
            return { failedUrls: topicResults.reduce((sum, result) => sum + result.failedUrls, 0) }
        } finally {
            ImageFetchRequestMetrics.observeRepublishFlush(Number(process.hrtime.bigint() - startedAt) / 1e9)
        }
    }

    private destination(waitMs: number): RepublishDestination | undefined {
        if (waitMs <= 0) {
            return { topic: this.frontierTopic, metricTopic: 'frontier', delayMs: 0 }
        }
        const tier = this.delayTiers.find((candidateTier) => candidateTier.delayMs >= waitMs)
        return tier ? { topic: tier.topic, metricTopic: tier.metricTopic, delayMs: tier.delayMs } : undefined
    }

    private planMessages(): PlannedRepublishMessage[] {
        const groups = new Map<string, PendingRepublish[]>()
        for (const item of this.pending) {
            const key = `${item.destination.topic}\0${item.candidate.registrableDomain}`
            const group = groups.get(key)
            if (group) {
                group.push(item)
            } else {
                groups.set(key, [item])
            }
        }
        return [...groups.values()].flatMap((items) => this.packGroup(items))
    }

    private packGroup(items: PendingRepublish[]): PlannedRepublishMessage[] {
        const plans: PlannedRepublishMessage[] = []
        let candidates: FetchCandidate[] = []
        let reasons: RepublishReason[] = []
        let recordBytes = EMPTY_FRONTIER_RECORD_BYTES
        const finishPlan = (): void => {
            if (candidates.length === 0) {
                return
            }
            plans.push({
                topic: items[0].destination.topic,
                metricTopic: items[0].destination.metricTopic,
                registrableDomain: items[0].candidate.registrableDomain,
                candidates,
                reasons,
            })
            candidates = []
            reasons = []
            recordBytes = EMPTY_FRONTIER_RECORD_BYTES
        }
        for (const item of items) {
            const candidateBytes = serializeFrontierRecord([item.candidate]).length - EMPTY_FRONTIER_RECORD_BYTES
            const nextRecordBytes = recordBytes + candidateBytes + (candidates.length > 0 ? 1 : 0)
            if (
                candidates.length > 0 &&
                (candidates.length === MAX_JOBS_PER_RECORD || nextRecordBytes > MAX_RECORD_BYTES)
            ) {
                finishPlan()
            }
            recordBytes += candidateBytes + (candidates.length > 0 ? 1 : 0)
            candidates.push(item.candidate)
            reasons.push(item.reason)
            if (recordBytes > MAX_RECORD_BYTES) {
                throw new Error('one image fetch republish job exceeds the Kafka record limit')
            }
        }
        finishPlan()
        return plans
    }

    private async publishTopic(
        metricTopic: RepublishTopic,
        plans: PlannedRepublishMessage[],
        deliveryState: RepublishDeliveryState
    ): Promise<RepublishFlushResult> {
        const startedAt = process.hrtime.bigint()
        const results = await Promise.all(
            plans.map((plan) =>
                this.republishes.run({
                    debugTag: plan.metricTopic,
                    fn: async (): Promise<RepublishDeliveryResult> => {
                        if (deliveryState.failed) {
                            return 'skipped'
                        }
                        if (performance.now() >= this.deadlineAtMonotonicMs) {
                            deliveryState.failed = true
                            deliveryState.deadlineExceeded = true
                            return 'skipped'
                        }
                        try {
                            await this.producer.produce({
                                topic: plan.topic,
                                key: Buffer.from(plan.registrableDomain),
                                value: serializeFrontierRecord(plan.candidates),
                            })
                            return 'published'
                        } catch {
                            deliveryState.failed = true
                            return 'failed'
                        }
                    },
                })
            )
        )
        let failedUrls = 0
        let attemptedMessages = 0
        const attemptedRegistrableDomains = new Set<string>()
        for (let index = 0; index < plans.length; index++) {
            const plan = plans[index]
            if (results[index] === 'skipped') {
                failedUrls += plan.candidates.length
                continue
            }
            attemptedMessages++
            attemptedRegistrableDomains.add(plan.registrableDomain)
            if (results[index] === 'failed') {
                failedUrls += plan.candidates.length
                this.recordFailedPlan(plan)
                continue
            }
            for (const reason of plan.reasons) {
                ImageFetchRequestMetrics.incRepublished(reason, metricTopic === 'frontier' ? 'frontier' : 'delay')
            }
        }
        if (attemptedMessages > 0) {
            ImageFetchRequestMetrics.observeRepublishBatch(
                metricTopic,
                attemptedMessages,
                attemptedRegistrableDomains.size,
                Number(process.hrtime.bigint() - startedAt) / 1e9
            )
        }
        return { failedUrls }
    }

    private recordFailedPlan(plan: PlannedRepublishMessage): void {
        logger.warn('🌐', 'ml_image_fetch_republish_failed', {
            topic: plan.topic,
            urls: plan.candidates.length,
        })
        for (const reason of plan.reasons) {
            ImageFetchRequestMetrics.incRepublishFailed(reason)
        }
    }
}
