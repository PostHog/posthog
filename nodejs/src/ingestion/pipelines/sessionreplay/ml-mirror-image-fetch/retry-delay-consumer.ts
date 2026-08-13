import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { logger } from '~/common/utils/logger'
import { delay } from '~/common/utils/utils'

import { RetryDelayMetrics } from './metrics'

export interface RetryDelayConsumerOptions {
    /** Where a ripe record goes. Always the frontier. */
    frontierTopic: string
    /** How long every record in this topic waits. It is a property of the topic, not of the record. */
    delayMs: number
    /** Called while the consumer sleeps, so the health check does not restart a pod that is working as designed. */
    heartbeat: () => void
    /** How often to beat during a wait. The health check fails a consumer silent for 60s, so the default sits well inside that. */
    heartbeatIntervalMs?: number
    /** True once the pod is shutting down. A wait of an hour would otherwise hold the rolling deploy until Kubernetes killed it. */
    isStopping?: () => boolean
}

const DEFAULT_HEARTBEAT_INTERVAL_MS = 10_000

/**
 * The consumer of one delay topic.
 *
 * Kafka has no delayed delivery, so a retry waits in a topic whose period is fixed and a consumer
 * holds it there. Every record in one topic waits the same period, which keeps the records in the
 * order they become ready and stops an hour-long wait sitting in front of a one minute wait.
 *
 * The consumer reads a record, waits out whatever is left of the period, and publishes it back to
 * the frontier unchanged. The record already carries its hop budget and its earliest fetch time, so
 * nothing here has to parse it.
 *
 * Two properties of this lane come from its deployment rather than from this file, and both are in
 * the README. Its `max.poll.interval.ms` must exceed the period of its topic, or the broker evicts
 * it mid-sleep. It runs one pod and no more, because adding consumers cannot make a record ripen
 * sooner.
 */
export class RetryDelayConsumer {
    constructor(
        private readonly producer: KafkaProducerWrapper,
        private readonly options: RetryDelayConsumerOptions
    ) {
        if (!Number.isFinite(options.delayMs) || options.delayMs <= 0) {
            throw new Error(`the retry delay consumer needs a positive delay, got ${options.delayMs}`)
        }
    }

    public async handleBatch(messages: Message[]): Promise<void> {
        for (const message of messages) {
            if (this.stopping()) {
                // The consumer stores offsets for the whole batch once this returns, so a record
                // left here is lost rather than held. That is the lesser cost: the alternative is
                // making a rolling deploy wait out a whole tier period. Requirement 21 would fix
                // it, and the README says it is not built.
                RetryDelayMetrics.incReleased('abandoned')
                return
            }
            const waitMs = this.remainingWaitMs(message)
            if (waitMs > 0) {
                RetryDelayMetrics.observeWait(waitMs / 1000)
                if (!(await this.sleepWithHeartbeat(waitMs))) {
                    RetryDelayMetrics.incReleased('abandoned')
                    return
                }
            }
            await this.release(message)
        }
    }

    private stopping(): boolean {
        return this.options.isStopping?.() ?? false
    }

    /**
     * What is left of this record's wait.
     *
     * Measured from when the record was written rather than from when it was read, so a consumer
     * that restarts does not begin the wait again. librdkafka reports an absent timestamp as -1,
     * which is not nullish, so a plain `??` would make the whole period look already spent.
     */
    private remainingWaitMs(message: Message): number {
        const writtenAtMs = message.timestamp !== undefined && message.timestamp > 0 ? message.timestamp : Date.now()
        return writtenAtMs + this.options.delayMs - Date.now()
    }

    /** False when the pod started shutting down during the wait, so the caller abandons the record. */
    private async sleepWithHeartbeat(waitMs: number): Promise<boolean> {
        const interval = this.options.heartbeatIntervalMs ?? DEFAULT_HEARTBEAT_INTERVAL_MS
        const deadline = Date.now() + waitMs
        while (Date.now() < deadline) {
            if (this.stopping()) {
                return false
            }
            this.options.heartbeat()
            await delay(Math.min(interval, deadline - Date.now()))
        }
        this.options.heartbeat()
        return !this.stopping()
    }

    /**
     * A record that cannot be published is dropped rather than retried here.
     *
     * Retrying inside this consumer would hold every record behind it for another period. The URL
     * has no crawl history entry, so the next session that refers to the image offers it again.
     */
    private async release(message: Message): Promise<void> {
        if (!message.value || !message.key) {
            RetryDelayMetrics.incReleased('malformed')
            return
        }
        try {
            await this.producer.produce({
                topic: this.options.frontierTopic,
                key: message.key,
                value: message.value,
            })
        } catch (error) {
            logger.warn('🌐', 'ml_image_fetch_retry_release_failed', {
                error: error instanceof Error ? error.name : 'unknown',
            })
            RetryDelayMetrics.incReleased('failed')
            return
        }
        RetryDelayMetrics.incReleased('released')
    }
}
