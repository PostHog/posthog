import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'
import { ZodError } from 'zod'

import { KafkaConsumerInterface, START_AT_EARLIEST, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger, serializeError } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { SES_WEBHOOKS_DLQ_OUTPUT } from '../outputs/outputs'
import { sesQueuedNotificationsCounter } from '../services/messaging/email-tracking.service'
import { SnsEnvelope, parseSnsEnvelope } from '../services/messaging/helpers/ses'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

const replayedDeadLettersCounter = new Counter({
    name: 'cdp_ses_webhooks_dlq_replay_total',
    help: 'Dead-lettered SES notifications the replay worker read, by outcome',
    labelNames: ['outcome'],
})

const REPLAY_GROUP_ID = 'cdp-ses-webhooks-dlq-replay'

type RecordOutcome = 'recorded' | 'unrecordable' | 'failed'

// The live consumer dead-letters every notification it cannot record, so one bad message cannot hold its partition.
// The replay reads that dead-letter topic. It skips an unrecordable notification, because it fails on every try.
// It throws on a failed one, because a database or Kafka outage can clear, and the offset must not commit past it.
export class CdpSesWebhooksConsumer extends CdpConsumerBase {
    protected name = 'CdpSesWebhooksConsumer'
    private kafkaConsumer: KafkaConsumerInterface

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        private options: { replayDeadLetters?: boolean } = {}
    ) {
        super(config, deps)
        this.kafkaConsumer = options.replayDeadLetters
            ? createKafkaConsumer(
                  { groupId: REPLAY_GROUP_ID, topic: config.CDP_SES_WEBHOOKS_DLQ_TOPIC },
                  START_AT_EARLIEST
              )
            : createKafkaConsumer({ groupId: 'cdp-ses-webhooks-consumer', topic: config.CDP_SES_WEBHOOKS_TOPIC })
    }

    public async processBatch(messages: Message[]): Promise<void> {
        for (const message of messages) {
            const outcome = await this.record(message)
            if (!this.options.replayDeadLetters) {
                if (outcome !== 'recorded') {
                    await this.deadLetter(message)
                }
                continue
            }
            const { topic, partition, offset } = message
            replayedDeadLettersCounter.labels({ outcome: outcome === 'unrecordable' ? 'skipped' : outcome }).inc()
            if (outcome === 'unrecordable') {
                logger.warn('[CdpSesWebhooksConsumer] Skipping a dead-lettered SES notification that cannot record', {
                    topic,
                    partition,
                    offset,
                })
            } else if (outcome === 'failed') {
                throw new Error(
                    `SES notification at ${topic}:${partition}:${offset} failed to record, so the replay stops ` +
                        'before committing past it'
                )
            }
        }
    }

    private async record(message: Message): Promise<RecordOutcome> {
        let envelope: SnsEnvelope
        try {
            envelope = parseSnsEnvelope(message.value?.toString() ?? '')
        } catch {
            logger.error('[CdpSesWebhooksConsumer] A message does not parse', {
                offset: message.offset,
                partition: message.partition,
            })
            counterParseError.labels({ error: 'unparseable_ses_notification' }).inc()
            return 'unrecordable'
        }
        try {
            const recording = await this.emailTrackingService.recordQueuedSesNotification(envelope)
            return recording.outcome === 'recorded' ? 'recorded' : 'unrecordable'
        } catch (error) {
            logger.error('[CdpSesWebhooksConsumer] Failed to record an SES notification', {
                snsMessageId: envelope.MessageId,
                error: serializeError(error),
            })
            // A ZodError is an SES event the handler cannot read, which fails again on every try.
            return error instanceof ZodError ? 'unrecordable' : 'failed'
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
