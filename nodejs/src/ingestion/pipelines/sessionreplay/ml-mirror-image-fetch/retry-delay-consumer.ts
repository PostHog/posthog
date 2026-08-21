import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { logger } from '~/common/utils/logger'
import { delay } from '~/common/utils/utils'

import { RetryDelayMetrics } from './metrics'

export interface RetryDelayConsumerOptions {
    frontierTopic: string
    /** The period every record in this topic waits. The period belongs to the topic, not to the record. */
    delayMs: number
    /** Called while the consumer sleeps, so the health check does not restart a pod that is working as designed. */
    heartbeat: () => void
    /** The default sits well inside CONSUMER_MAX_HEARTBEAT_INTERVAL_MS (30s), which binds before the loop stall threshold. */
    heartbeatIntervalMs?: number
    /** True once the pod is shutting down. A wait of an hour would otherwise hold the rolling deploy until Kubernetes killed it. */
    isStopping?: () => boolean
    /**
     * Called only for a record this consumer finished with. The consumer that owns this one stores
     * offsets for a whole batch once the handler returns, whatever the handler did with the
     * records, so a record abandoned mid-wait would commit and never be seen again. Requirement 21.
     */
    storeOffset: (message: Message) => void
}

const DEFAULT_HEARTBEAT_INTERVAL_MS = 10_000

/**
 * The consumer of one delay topic.
 *
 * Kafka has no delayed delivery, so a retry waits in a topic whose period is fixed and a consumer
 * holds it there. Every record in one topic waits the same period, so the records leave in the
 * order they become ready.
 *
 * The record already carries its hop budget and its earliest fetch time, so nothing here parses it.
 *
 * Two properties of this lane live outside this file, and both are in the README. Its
 * `max.poll.interval.ms` must exceed the period of its topic, or the broker evicts it mid-sleep. It
 * runs one pod and no more, because adding consumers cannot make a record become ready sooner.
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
                // The record stays where it is, with no offset stored. The next pod to own this
                // partition reads it again and waits out what is left of its period, measured from
                // when it was written. Requirement 21.
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
            if (!(await this.release(message))) {
                // Thrown, not returned. Returning holds this batch and no more: the next poll reads
                // the records after it and stores one of their offsets, and an offset is a high
                // water mark, so that commits this record too. A throw leaves the poll loop, so
                // nothing is stored and the record is read again. Requirement 21.
                throw new Error('the image fetch retry lane could not publish a record back to the frontier')
            }
            this.options.storeOffset(message)
        }
    }

    private stopping(): boolean {
        return this.options.isStopping?.() ?? false
    }

    /**
     * Measured from when the record was written rather than from when it was read, so a consumer
     * that restarts does not begin the wait again. librdkafka reports an absent timestamp as -1,
     * which is not nullish, so a plain `??` would make the whole period look already spent.
     */
    private remainingWaitMs(message: Message): number {
        const writtenAtMs = message.timestamp !== undefined && message.timestamp > 0 ? message.timestamp : Date.now()
        // Clamped to the period, because the timestamp comes from whichever pod wrote the record.
        // A clock ahead of this one would otherwise hold the record for longer than its tier, and
        // the tier period is the whole reason a record can be held here at all.
        return Math.min(this.options.delayMs, writtenAtMs + this.options.delayMs - Date.now())
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
     * True when this consumer is finished with the record, whether it went out or can never go out.
     *
     * A failed produce returns false, because reading the record again is the only way it comes
     * back. Nothing else holds it.
     */
    private async release(message: Message): Promise<boolean> {
        if (!message.value || !message.key) {
            // The offset stores anyway. This record can never be released, and holding its offset
            // would stop the partition rather than fix it.
            RetryDelayMetrics.incReleased('malformed')
            return true
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
            return false
        }
        RetryDelayMetrics.incReleased('released')
        return true
    }
}
