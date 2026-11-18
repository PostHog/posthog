import { Message } from 'node-rdkafka'
import { ZodError } from 'zod'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
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
        let next = 0
        const errors: unknown[] = []
        const recordNext = async (): Promise<void> => {
            while (next < messages.length && errors.length === 0) {
                const message = messages[next++]
                try {
                    const skipReason = await this.record(message)
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
        }
        if (errors.length > 0) {
            throw errors[0]
        }
    }

    private async record(message: Message): Promise<SkipReason | null> {
        let envelope: SnsEnvelope
        try {
            envelope = parseSnsEnvelope(message.value?.toString() ?? '')
        } catch (error) {
            counterParseError.labels({ error: 'unparseable_ses_notification' }).inc()
            return error instanceof ZodError ? 'not_an_sns_envelope' : 'unparseable'
        }
        try {
            const recording = await this.emailTrackingService.recordQueuedSesNotification(envelope)
            return recording.outcome === 'recorded' ? null : 'rejected'
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
