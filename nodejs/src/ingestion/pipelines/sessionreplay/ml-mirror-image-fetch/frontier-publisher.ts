import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { logger } from '~/common/utils/logger'

import { FetchCandidate, RepublishReason, serializeFrontierRecord } from './collected-urls-record'
import type { ImageFetchResult } from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'

export interface DelayTier {
    topic: string
    delayMs: number
}

export interface FrontierPublisherOptions {
    frontierTopic: string
    scrubTopic: string
    delayTiers: DelayTier[]
    maxConcurrentImagePublishes: number
}

export type RepublishResult = 'published' | 'refused_delay' | 'failed'

export class FrontierPublisher {
    private readonly delayTiers: DelayTier[]
    private readonly imagePublishes: ConcurrencyController

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
        this.imagePublishes = new ConcurrencyController(options.maxConcurrentImagePublishes)
    }

    public async republish(
        candidate: FetchCandidate,
        target: Pick<FetchCandidate, 'currentUrl' | 'host' | 'origin' | 'registrableDomain'>,
        reason: RepublishReason,
        waitMs = 0
    ): Promise<RepublishResult> {
        const spendsHop = reason === 'redirect' || reason === 'retry'
        const remainingHops = candidate.remainingHops - (spendsHop ? 1 : 0)
        if (remainingHops <= 0) {
            return 'refused_delay'
        }

        const effectiveWaitMs = reason === 'retry' ? Math.max(waitMs, this.delayTiers[0].delayMs) : waitMs
        const tier =
            effectiveWaitMs > 0
                ? this.delayTiers.find((candidateTier) => candidateTier.delayMs >= effectiveWaitMs)
                : undefined
        if (effectiveWaitMs > 0 && !tier) {
            return 'refused_delay'
        }
        const nowMs = Date.now()
        const republished: FetchCandidate = {
            ...candidate,
            ...target,
            remainingHops,
            notBeforeMs: tier ? nowMs + tier.delayMs : 0,
            republishCount: candidate.republishCount + 1,
            lastRepublishReason: reason,
        }
        const topic = tier?.topic ?? this.options.frontierTopic
        try {
            await this.producer.produce({
                topic,
                key: Buffer.from(target.registrableDomain),
                value: serializeFrontierRecord([republished]),
            })
        } catch (error) {
            logger.warn('🌐', 'ml_image_fetch_republish_failed', {
                reason,
                topic,
                error: error instanceof Error ? error.name : 'unknown',
            })
            ImageFetchRequestMetrics.incRepublishFailed(reason)
            return 'failed'
        }
        ImageFetchRequestMetrics.incRepublished(reason, tier ? 'delay' : 'frontier')
        return 'published'
    }

    public async publishImage(candidate: FetchCandidate, result: ImageFetchResult): Promise<void> {
        if (!result.bytes || !result.contentType) {
            throw new Error('an image publish needs response bytes and a content type')
        }
        const bytes = result.bytes
        const headers: Record<string, string> = { 'content-type': result.contentType }
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
