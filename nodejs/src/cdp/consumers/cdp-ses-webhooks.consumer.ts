import { Message } from 'node-rdkafka'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger, serializeError } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { SES_WEBHOOKS_DLQ_OUTPUT } from '../outputs/outputs'
import { sesQueuedNotificationsCounter } from '../services/messaging/email-tracking.service'
import { SnsEnvelope, parseSnsEnvelope } from '../services/messaging/helpers/ses'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

// A notification that fails to record goes to the dead-letter topic, so one bad message cannot hold its partition.
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
            if (!(await this.record(message))) {
                await this.deadLetter(message)
            }
        }
    }

    private async record(message: Message): Promise<boolean> {
        let envelope: SnsEnvelope
        try {
            envelope = parseSnsEnvelope(message.value?.toString() ?? '')
        } catch {
            logger.error('[CdpSesWebhooksConsumer] A message does not parse', {
                offset: message.offset,
                partition: message.partition,
            })
            counterParseError.labels({ error: 'unparseable_ses_notification' }).inc()
            return false
        }
        try {
            const recording = await this.emailTrackingService.recordQueuedSesNotification(envelope)
            return recording.outcome === 'recorded'
        } catch (error) {
            logger.error('[CdpSesWebhooksConsumer] Failed to record an SES notification', {
                snsMessageId: envelope.MessageId,
                error: serializeError(error),
            })
            return false
        }
    }

    private async deadLetter(message: Message): Promise<void> {
        await this.outputs.produce(SES_WEBHOOKS_DLQ_OUTPUT, {
            key: message.key ? Buffer.from(message.key) : null,
            value: message.value ?? null,
        })
        sesQueuedNotificationsCounter.inc({ stage: 'dead_lettered' })
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
