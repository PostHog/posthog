import { Message } from 'node-rdkafka'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger, serializeError } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { sesQueuedNotificationsCounter } from '../services/messaging/email-tracking.service'
import { SnsEnvelope, parseSnsEnvelope } from '../services/messaging/helpers/ses'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

type RecordFailure = {
    reason: 'unparseable' | 'rejected' | 'recording_failed'
    error?: ReturnType<typeof serializeError>
}

// A notification that fails to record is logged, counted and skipped, so one bad message cannot hold its
// partition. SNS drops a notification the same way after its last retry.
export class CdpSesWebhooksConsumer extends CdpConsumerBase {
    protected name = 'CdpSesWebhooksConsumer'
    private kafkaConsumer: KafkaConsumerInterface

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-ses-webhooks-consumer',
            topic: config.CDP_SES_WEBHOOKS_TOPIC,
        })
    }

    public async processBatch(messages: Message[]): Promise<void> {
        for (const message of messages) {
            const failure = await this.record(message)
            if (failure) {
                logger.error('[CdpSesWebhooksConsumer] Skipping an SES notification that failed to record', {
                    topic: message.topic,
                    partition: message.partition,
                    offset: message.offset,
                    ...failure,
                })
                sesQueuedNotificationsCounter.inc({ stage: 'skipped' })
            }
        }
    }

    private async record(message: Message): Promise<RecordFailure | null> {
        let envelope: SnsEnvelope
        try {
            envelope = parseSnsEnvelope(message.value?.toString() ?? '')
        } catch {
            counterParseError.labels({ error: 'unparseable_ses_notification' }).inc()
            return { reason: 'unparseable' }
        }
        try {
            const recording = await this.emailTrackingService.recordQueuedSesNotification(envelope)
            return recording.outcome === 'recorded' ? null : { reason: 'rejected' }
        } catch (error) {
            return { reason: 'recording_failed', error: serializeError(error) }
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
