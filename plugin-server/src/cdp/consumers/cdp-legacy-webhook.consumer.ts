import { instrumentFn } from '~/common/tracing/tracing-utils'
import { KafkaConsumer } from '~/kafka/consumer'

import { HealthCheckResult, Hub } from '../../types'
import { logger } from '../../utils/logger'
import { LegacyWebhookService } from '../legacy-webhooks/legacy-webhook-service'
import { CdpConsumerBase } from './cdp-base.consumer'

/**
 * This consumer processes webhook events from the legacy webhooks system - this is the "hooks" table that used to be filled via Zapier.
 * Now the only path for creation is via a hog function but this just exists for now to keep non-migrated webhooks working.
 */

export class CdpLegacyWebhookConsumer extends CdpConsumerBase {
    protected name = 'CdpLegacyWebhookConsumer'
    protected kafkaConsumer: KafkaConsumer
    protected legacyWebhookService: LegacyWebhookService

    constructor(hub: Hub) {
        super(hub)

        this.kafkaConsumer = new KafkaConsumer({
            groupId: hub.CDP_LEGACY_WEBHOOK_CONSUMER_GROUP_ID,
            topic: hub.CDP_LEGACY_WEBHOOK_CONSUMER_TOPIC,
        })

        this.legacyWebhookService = new LegacyWebhookService(hub)

        logger.info('🔁', `CdpLegacyWebhookConsumer setup`)
    }

    public async start(): Promise<void> {
        await super.start()
        await this.legacyWebhookService.start()
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpLegacyWebhookConsumer.handleEachBatch', async () => {
                return await this.legacyWebhookService.processBatch(messages)
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        await this.legacyWebhookService.stop()
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
