import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { logger } from '~/common/utils/logger'

import { FetchCandidate } from './collected-urls-record'
import { ImageFetchRequestMetrics } from './metrics'

/**
 * One delay topic. Every message in it waits the same period, which is what keeps the messages in
 * the order they become ready and stops an hour-long wait sitting in front of a one minute wait.
 */
export interface DelayTier {
    topic: string
    delayMs: number
}

export interface FrontierPublisherOptions {
    frontierTopic: string
    /** Ordered by delay, shortest first. The scheduler picks the first tier that covers the wait. */
    delayTiers: DelayTier[]
}

/** Why a URL is going back to Kafka rather than being finished with. */
export type RepublishReason = 'redirect' | 'retry'

/**
 * Puts a URL back into the frontier, either at once or after a wait.
 *
 * Two things use this. A redirect that leaves the registrable domain cannot be followed here,
 * because the budget for the new domain belongs to whichever consumer owns its partition, so the
 * target goes back as a new candidate. A transient failure cannot be retried here either, because
 * waiting in place holds the partition against every other site on it.
 *
 * Both spend a hop, so neither can go around forever. See the README, requirements 7 and 11 to 15.
 */
export class FrontierPublisher {
    constructor(
        private readonly producer: KafkaProducerWrapper,
        private readonly options: FrontierPublisherOptions
    ) {
        if (options.delayTiers.length === 0) {
            throw new Error('the image fetch lane needs at least one delay tier to retry with')
        }
    }

    /**
     * Send one URL back to the frontier, keyed by the domain given.
     *
     * The ref is the original one. The recording points at that ref, and a hash of a redirect
     * target matches nothing, so a new ref would leave the image unreachable. Requirement 10.
     */
    public async republish(
        candidate: FetchCandidate,
        target: { url: string; host: string; domain: string },
        reason: RepublishReason,
        waitMs = 0
    ): Promise<boolean> {
        const hopsRemaining = candidate.hopsRemaining - 1
        if (hopsRemaining <= 0) {
            return false
        }
        const tier = waitMs > 0 ? this.tierFor(waitMs) : undefined
        const topic = tier?.topic ?? this.options.frontierTopic
        const value = Buffer.from(
            JSON.stringify({
                v: 1,
                pseudoTeam: candidate.pseudoTeam,
                capturedAtMs: candidate.capturedAtMs,
                hopsRemaining,
                notBeforeMs: tier ? Date.now() + tier.delayMs : 0,
                urls: [{ ref: candidate.ref, url: target.url, host: target.host }],
            })
        )

        try {
            await this.producer.produce({ topic, key: Buffer.from(target.domain), value })
        } catch (error) {
            // The URL is left unrecorded, so the next session that refers to it offers it again.
            // Nothing is thrown: one failed produce must not abandon the rest of the batch.
            logger.warn('🌐', 'ml_image_fetch_republish_failed', {
                reason,
                topic,
                error: error instanceof Error ? error.name : 'unknown',
            })
            ImageFetchRequestMetrics.incRepublishFailed(reason)
            return false
        }
        ImageFetchRequestMetrics.incRepublished(reason, topic)
        return true
    }

    /**
     * The first tier whose delay covers the wait, or the longest one.
     *
     * A wait longer than every tier comes back early, spends another hop, and waits again. That is
     * cheaper than a tier long enough for the worst `Retry-After` a site can name, and the host
     * budget refuses an early arrival without sending anything.
     */
    private tierFor(waitMs: number): DelayTier {
        return this.options.delayTiers.find((tier) => tier.delayMs >= waitMs) ?? this.options.delayTiers.at(-1)!
    }
}
