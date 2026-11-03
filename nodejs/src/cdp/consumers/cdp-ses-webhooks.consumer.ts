import { Message } from 'node-rdkafka'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

/**
 * Records the SES notifications the webhook verified and queued: metrics, log entries and
 * suppression-list writes.
 *
 * The work sits here rather than in the request so that a datastore failure retries against Kafka,
 * which replays from the offset it did not commit, instead of against SNS, which redelivers a
 * notification whose metrics the failed attempt had already partly recorded.
 */
export class CdpSesWebhooksConsumer extends CdpConsumerBase {
    protected name = 'CdpSesWebhooksConsumer'
    protected kafkaConsumer: KafkaConsumerInterface

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-ses-webhooks-consumer',
            // From config, not the constant: the webhook produces to whatever the registry
            // resolved, so reading the constant would miss an overridden topic entirely.
            topic: config.CDP_SES_WEBHOOKS_TOPIC,
        })
    }

    public async processBatch(messages: Message[]): Promise<void> {
        for (const message of messages) {
            let body: unknown
            try {
                body = parseJSON(message.value!.toString())
            } catch (error) {
                // The webhook parsed and verified this payload before producing it, so an
                // unreadable one is corruption that no replay can fix. Skipped rather than
                // thrown, which would stall the partition behind it forever.
                logger.error('[CdpSesWebhooksConsumer] Dropping unparseable message', { error })
                counterParseError.labels({ error: 'unparseable_ses_notification' }).inc()
                continue
            }
            await this.emailTrackingService.processSesNotification(body)
        }
    }

    public override async start(): Promise<void> {
        await super.start()
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, { size: messages.length })
            return await instrumentFn('cdpSesWebhooksConsumer.handleEachBatch', async () => {
                await this.processBatch(messages)
                return { backgroundTask: Promise.resolve() }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
