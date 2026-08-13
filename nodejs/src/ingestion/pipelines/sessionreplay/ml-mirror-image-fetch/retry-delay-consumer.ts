import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { logger } from '~/common/utils/logger'
import { delay } from '~/common/utils/utils'

import { RetryDelayMetrics } from './metrics'

export interface RetryDelayConsumerOptions {
    /** Where a record goes once its wait ends. Always the frontier. */
    frontierTopic: string
    /** How long every record in this topic waits. It is a property of the topic, not of the record. */
    delayMs: number
    /** Called while the consumer sleeps, so the health check does not restart a pod that is working as designed. */
    heartbeat: () => void
    /** How often to beat during a wait. The health check fails a consumer silent for 60s, so the default sits well inside that. */
    heartbeatIntervalMs?: number
    /** True once the pod is shutting down. A wait of an hour would otherwise hold the rolling deploy until Kubernetes killed it. */
    isStopping?: () => boolean
    /**
     * Marks one record as done, so its offset commits and the next poll starts after it.
     *
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
 * holds it there. Every record in one topic waits the same period, which keeps the records in the
 * order they become ready and stops an hour-long wait sitting in front of a one minute wait.
 *
 * The consumer reads a record, waits out whatever is left of the period, and publishes it back to
 * the frontier unchanged. The record already carries its hop budget and its earliest fetch time, so
 * nothing here has to parse it.
 *
 * Two properties of this lane come from its deployment rather than from this file, and both are in
 * the README. Its `max.poll.interval.ms` must exceed the period of its topic, or the broker evicts
 * it mid-sleep. It runs one pod and no more, because adding consumers cannot make a record become
 * ready sooner.
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
                // Left where it is, with no offset stored. The next pod to own this partition reads
                // it again and waits out whatever is left of its period, measured from when it was
                // written. Requirement 21.
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
                // The rest of the batch stays where it is. An offset is a high water mark, so
                // storing a later one would commit this record as well. Requirement 21.
                return
            }
            this.options.storeOffset(message)
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
     * True when this consumer is finished with the record, whether it went out or can never go out.
     *
     * A produce that failed returns false, and the caller stops the batch there. Reading the record
     * again is the only way it comes back, because nothing else holds it.
     */
    private async release(message: Message): Promise<boolean> {
        if (!message.value || !message.key) {
            // Stored anyway. This record can never be released, and holding its offset would stop
            // the partition rather than fix it.
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
