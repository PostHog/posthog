import { initializePrometheusLabels } from '~/common/api/router'
import { KafkaConsumer } from '~/common/kafka/consumer/consumer-v1'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { SessionReplayProducerName } from '~/ingestion/pipelines/sessionreplay/config'
import { replayBatch } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/dlq-replay'
import { createProducerRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/producer-registry'
import { INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER } from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'

import { logger } from '../common/utils/logger'
import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import {
    IngestionSessionReplayMlMirrorServerConfig,
    buildMlMirrorServerConfig,
} from './ingestion-session-replay-ml-mirror-server'

/**
 * Pushes images the scrub sidecar could not process back onto the topic they came from.
 *
 * Run deliberately, after the sidecar bug that parked them has been fixed and deployed, by scaling
 * this to one replica. It reads to the end of the dead-letter topic and stops, so it drains what is
 * there and does not sit re-driving whatever arrives next.
 *
 * That it stops is the point rather than an implementation detail. A dead-letter topic earns its
 * keep by holding images still: something continuously pushing them back would either empty the
 * quarantine before anyone had looked at it, or, against a sidecar that is still broken, cycle the
 * same images between the two topics and spend scrub capacity on work already known to fail. The
 * lane has no capacity to spare for that.
 */
export class IngestionSessionReplayMlImageScrubDlqReplayServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionSessionReplayMlMirrorServerConfig
    private producerRegistry?: KafkaProducerRegistry<SessionReplayProducerName>

    constructor(config: Partial<IngestionSessionReplayMlMirrorServerConfig> = {}) {
        this.config = buildMlMirrorServerConfig(config)
        this.lifecycle = new ServerLifecycle(this.config)
    }

    async start(): Promise<void> {
        return this.lifecycle.start(
            () => this.startServices(),
            () => this.getCleanupResources()
        )
    }

    async stop(error?: Error): Promise<void> {
        return this.lifecycle.stop(() => this.getCleanupResources(), error)
    }

    private async startServices(): Promise<void> {
        initializePrometheusLabels(this.config.INGESTION_PIPELINE, this.config.INGESTION_LANE)

        const dlqTopic = this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC
        if (!dlqTopic) {
            throw new Error('SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC must be set to replay from it')
        }
        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const producer = this.producerRegistry.getProducer(INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER)

        // A separate group from the scrub consumer's, and its own topic, so a replay run cannot
        // disturb the offsets of the lane it is feeding.
        const consumer = new KafkaConsumer({
            topic: dlqTopic,
            groupId: `${this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_GROUP_ID}-dlq-replay`,
            autoCommit: true,
            autoOffsetStore: true,
            // Committing as it goes means an interrupted run resumes rather than starting over and
            // replaying images the fixed sidecar has already taken.
            callEachBatchWhenEmpty: true,
        })

        let idlePolls = 0
        let replayed = 0
        let exhausted = 0
        await consumer.connect(async (messages) => {
            if (messages.length === 0) {
                idlePolls += 1
                // Two consecutive empty polls means the topic is drained as of now. Stopping here is
                // what makes the run bounded: the operator scaled this up to clear a backlog, not to
                // leave something watching the quarantine.
                if (idlePolls >= 2) {
                    logger.info('☠️', 'image_scrub_dlq_replay_complete', { replayed, exhausted })
                    void this.stop()
                }
                return
            }
            idlePolls = 0
            const outcome = await replayBatch(
                messages,
                producer,
                this.config.INGESTION_SESSIONREPLAY_OUTPUT_ML_IMAGE_SCRUB_TOPIC
            )
            replayed += outcome.replayed
            exhausted += outcome.exhausted
            logger.info('☠️', 'image_scrub_dlq_replay_progress', { replayed, exhausted })
        })

        this.lifecycle.services.push({
            id: 'session-replay-ml-image-scrub-dlq-replay',
            onShutdown: () => consumer.disconnect(),
            healthcheck: () => consumer.isHealthy(),
        })
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [],
            additionalCleanup: () => this.producerRegistry?.disconnectAll(),
        }
    }
}
