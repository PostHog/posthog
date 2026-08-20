import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { logger } from '~/common/utils/logger'

import { FetchCandidate } from './collected-urls-record'
import { ImageFetchRequestMetrics } from './metrics'

/** One delay topic. Every record in it waits the same period, so the records leave in the order they become ready. */
export interface DelayTier {
    topic: string
    delayMs: number
}

export interface FrontierPublisherOptions {
    frontierTopic: string
    /** Ordered by delay, shortest first, because the publisher takes the first tier that covers the wait. */
    delayTiers: DelayTier[]
}

export type RepublishReason = 'redirect' | 'retry' | 'not_ready'

/**
 * Sends a URL back to the frontier, at once or after a wait.
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
     * The ref stays the original one. The recording points at that ref, and a hash of a redirect
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
        // A retry always waits, even when nothing named a period. A timeout, a connection error,
        // and a batch that ran out of time name none, and publishing those straight back to the
        // frontier is a loop: the consumer reads the record, meets the same condition, and
        // publishes it again, spending a hop each lap until the URL is written off unfetched. A URL
        // that arrived early waits for the same reason, for a period it already knows. A redirect
        // goes back at once, because its target is a different domain with its own budget.
        const tier = reason === 'redirect' ? undefined : this.tierFor(Math.max(waitMs, 1))
        const topic = tier?.topic ?? this.options.frontierTopic
        const value = Buffer.from(
            JSON.stringify({
                v: 1,
                pseudoTeam: candidate.pseudoTeam,
                capturedAtMs: candidate.capturedAtMs,
                hopsRemaining,
                // The longer of the wait asked for and the period of the tier holding it. A wait
                // past the longest tier arrives before it is due, and the consumer sends it back
                // for the rest. Requirement 15.
                notBeforeMs: tier ? Date.now() + Math.max(waitMs, tier.delayMs) : 0,
                urls: [{ ref: candidate.ref, url: target.url, host: target.host }],
            })
        )

        try {
            await this.producer.produce({ topic, key: Buffer.from(target.domain), value })
        } catch (error) {
            // Nothing throws here, because one failed produce must not abandon the rest of the
            // batch. The caller counts the false return and holds the batch instead. Requirement 21.
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
     * A wait longer than every tier comes back early, spends another hop, and waits again. That is
     * cheaper than a tier long enough for the worst `Retry-After` a site can name, and the host
     * budget refuses an early arrival without sending anything.
     */
    private tierFor(waitMs: number): DelayTier {
        return this.options.delayTiers.find((tier) => tier.delayMs >= waitMs) ?? this.options.delayTiers.at(-1)!
    }
}
