import { Message } from 'node-rdkafka'
import { ZodError } from 'zod'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger, serializeError } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { sesQueuedNotificationsCounter } from '../services/messaging/email-tracking.service'
import { SnsEnvelope, parseSnsEnvelope } from '../services/messaging/helpers/ses'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

type SkipReason = 'unparseable' | 'not_an_sns_envelope' | 'invalid_ses_event' | 'rejected'

// Smaller than the default, because the whole batch must record within the 30s heartbeat health check. With 10 in
// flight and one Kafka flush per batch, 200 notifications take a few seconds.
const SES_NOTIFICATIONS_PER_BATCH = 200

// Each write of a notification is an atomic Postgres upsert, an atomic Redis script, or a Kafka append, so
// notifications can record in any order. The topic is keyed by SNS message id, so other pods already record
// notifications to the same recipient at the same time.
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
        // A failure stops new notifications and waits for those in flight, so no write outlives the failed batch.
        await Promise.all(Array.from({ length: SES_NOTIFICATIONS_IN_FLIGHT }, recordNext))
        if (errors.length > 0) {
            throw errors[0]
        }
        // Offsets commit after processBatch resolves, so the batch commits only after Kafka acks its writes.
        await this.emailTrackingService.flush()
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
