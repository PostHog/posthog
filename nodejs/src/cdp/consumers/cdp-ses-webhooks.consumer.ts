import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'
import { ZodError } from 'zod'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { RedisClientPipeline, RedisPipelineResults } from '~/common/redis/redis-v2'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger, serializeError } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { sesQueuedNotificationsCounter } from '../services/messaging/email-tracking.service'
import { SES_NOTIFICATIONS_PER_BATCH } from '../services/messaging/helpers/ses'
import { SnsEnvelope, parseSnsEnvelope } from '../services/messaging/helpers/sns-envelope'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

type SkipReason = 'unparseable' | 'not_an_sns_envelope' | 'invalid_ses_event' | 'rejected'

// Safe in any order: every write is an atomic upsert, an atomic Redis script or a Kafka append.
const SES_NOTIFICATIONS_IN_FLIGHT = 10

const sesNotificationRecordedKey = (snsMessageId: string): string =>
    `@posthog/ses-notification-recorded/${snsMessageId}`
// Counted from the last batch that wrote or read the mark. Long enough to cover SNS retries and Kafka redeliveries,
// short enough to cap the key count and to let a replay after an outage record again.
const SES_NOTIFICATION_RECORDED_TTL_SECONDS = 60 * 60
const SES_NOTIFICATION_RECORDED_DEADLINE_MS = 500

const sesRecordedMarksUnavailableCounter = new Counter({
    name: 'email_tracking_ses_recorded_marks_unavailable_total',
    help: 'Batches whose recorded-notification marks Redis could not read or write in full, so a redelivery can count again',
    labelNames: ['operation'],
})

type BatchMarks = { skip: Set<string>; recorded: string[] }

// A notification that can never record is skipped, as SNS drops it after its last retry, so it cannot hold its
// partition. Any other error fails the batch so Kafka redelivers it once the datastore recovers, which can count
// a half-recorded notification again.
export class CdpSesWebhooksConsumer extends CdpConsumerBase {
    protected name = 'CdpSesWebhooksConsumer'
    private kafkaConsumer: KafkaConsumerInterface

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-ses-webhooks-consumer',
            topic: config.CDP_SES_WEBHOOKS_TOPIC,
            fetchBatchSize: SES_NOTIFICATIONS_PER_BATCH,
        })
    }

    public async processBatch(messages: Message[]): Promise<void> {
        const marks: BatchMarks = { skip: await this.recordedEarlier(messages), recorded: [] }
        let next = 0
        const errors: unknown[] = []
        const recordNext = async (): Promise<void> => {
            while (next < messages.length && errors.length === 0) {
                const message = messages[next++]
                try {
                    const skipReason = await this.record(message, marks)
                    if (skipReason) {
                        logger.error('[CdpSesWebhooksConsumer] Skipping an SES notification that can never record', {
                            topic: message.topic,
                            partition: message.partition,
                            offset: message.offset,
                            reason: skipReason,
                        })
                        sesQueuedNotificationsCounter.inc({ stage: 'skipped' })
                    }
                } catch (error) {
                    errors.push(error)
                }
            }
        }
        await Promise.all(Array.from({ length: SES_NOTIFICATIONS_IN_FLIGHT }, recordNext))
        // Flush a failed batch too: its recorded opens already grew the unique-person counters, which a redelivery won't.
        try {
            await this.emailTrackingService.flush()
        } catch (error) {
            if (errors.length === 0) {
                throw error
            }
            logger.error('[CdpSesWebhooksConsumer] Failed to flush a failed batch', { error: serializeError(error) })
            throw errors[0]
        }
        await this.markRecorded(marks.recorded)
        if (errors.length > 0) {
            throw errors[0]
        }
    }

    private async record(message: Message, marks: BatchMarks): Promise<SkipReason | null> {
        let envelope: SnsEnvelope
        try {
            envelope = parseSnsEnvelope(message.value?.toString() ?? '')
        } catch (error) {
            counterParseError.labels({ error: 'unparseable_ses_notification' }).inc()
            return error instanceof ZodError ? 'not_an_sns_envelope' : 'unparseable'
        }
        if (marks.skip.has(envelope.MessageId)) {
            sesQueuedNotificationsCounter.inc({ stage: 'redelivered' })
            return null
        }
        marks.skip.add(envelope.MessageId)
        try {
            const recording = await this.emailTrackingService.recordQueuedSesNotification(envelope)
            if (recording.outcome !== 'recorded') {
                return 'rejected'
            }
            marks.recorded.push(envelope.MessageId)
            return null
        } catch (error) {
            // A ZodError is an SES event that does not match the schema, so every retry fails the same way.
            if (error instanceof ZodError) {
                return 'invalid_ses_event'
            }
            logger.error('[CdpSesWebhooksConsumer] Failed to record an SES notification, so the batch fails', {
                topic: message.topic,
                partition: message.partition,
                offset: message.offset,
                error: serializeError(error),
            })
            sesQueuedNotificationsCounter.inc({ stage: 'failed' })
            throw error
        }
    }

    // The queue keys each message by its SNS MessageId.
    private async recordedEarlier(messages: Message[]): Promise<Set<string>> {
        const ids = [...new Set(messages.flatMap((message) => (message.key ? [message.key.toString()] : [])))]
        if (ids.length === 0) {
            return new Set()
        }
        const results = await this.recordedMarksPipeline('read', (pipeline) => {
            // One command per key, because a multi-key command fails with CROSSSLOT across cluster slots.
            for (const id of ids) {
                pipeline.getex(sesNotificationRecordedKey(id), 'EX', SES_NOTIFICATION_RECORDED_TTL_SECONDS)
            }
        })
        return new Set(ids.filter((_, index) => results?.[index]?.[1] != null))
    }

    private async markRecorded(snsMessageIds: string[]): Promise<void> {
        if (snsMessageIds.length === 0) {
            return
        }
        await this.recordedMarksPipeline('write', (pipeline) => {
            for (const id of snsMessageIds) {
                pipeline.set(sesNotificationRecordedKey(id), '1', 'EX', SES_NOTIFICATION_RECORDED_TTL_SECONDS)
            }
        })
    }

    // failOpen does not cover a pool that cannot hand out a client in time, so that error is caught here.
    private async recordedMarksPipeline(
        operation: 'read' | 'write',
        addCommands: (pipeline: RedisClientPipeline) => void
    ): Promise<RedisPipelineResults | null> {
        const results = await this.redis
            .usePipeline(
                {
                    name: `ses-notification-recorded-${operation}`,
                    failOpen: true,
                    deadlineMs: SES_NOTIFICATION_RECORDED_DEADLINE_MS,
                },
                addCommands
            )
            .catch(() => null)
        if (results === null || results.some(([error]) => error)) {
            sesRecordedMarksUnavailableCounter.inc({ operation })
        }
        return results
    }

    public override async start(): Promise<void> {
        await super.start()
        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn('cdpSesWebhooksConsumer.handleEachBatch', async () => {
                await this.processBatch(messages)
                return { backgroundTask: Promise.resolve() }
            })
        })
    }

    public override async stop(): Promise<void> {
        await this.kafkaConsumer.disconnect()
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
