import { S3Client } from '@aws-sdk/client-s3'

import { initializePrometheusLabels } from '~/common/api/router'
import { KAFKA_SESSION_REPLAY_IMAGE_SCRUB } from '~/common/config/kafka-topics'
import { KafkaConsumer, KafkaConsumerConfig } from '~/common/kafka/consumer/consumer-v1'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { SessionReplayProducerName } from '~/ingestion/pipelines/sessionreplay/config'
import { KafkaDeadLetterSink } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/dead-letter-sink'
import { ImageBatcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/image-batcher'
import { ImageShardStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/image-shard-store'
import { ScrubClient } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/scrub-client'
import { createProducerRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/producer-registry'
import { INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER } from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'
import { buildSessionRecordingS3Client } from '~/ingestion/pipelines/sessionreplay/shared/s3-client'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import {
    IngestionSessionReplayMlMirrorServerConfig,
    buildMlMirrorServerConfig,
} from './ingestion-session-replay-ml-mirror-server'

// A scrub + S3-write batch blocks the poll loop (which only heartbeats once per batch) for up to minutes, so
// we refresh the heartbeat this often during it. Must stay under CONSUMER_MAX_HEARTBEAT_INTERVAL_MS (30s).
const BATCH_HEARTBEAT_INTERVAL_MS = 10_000

export function requireS3Client(client: S3Client | null): S3Client {
    if (!client) {
        throw new Error('SESSION_RECORDING_V2_S3_* must be configured for the image-scrub consumer')
    }
    return client
}

export function buildImageScrubConsumerConfig(config: IngestionSessionReplayMlMirrorServerConfig): KafkaConsumerConfig {
    return {
        topic: KAFKA_SESSION_REPLAY_IMAGE_SCRUB,
        groupId: config.SESSION_RECORDING_ML_IMAGE_SCRUB_GROUP_ID,
        autoCommit: true,
        autoOffsetStore: false,
        callEachBatchWhenEmpty: true,
        // Far below the 500 default, because this lane's batch has no time limit: a busy sidecar is
        // waited on rather than dropped, so batch duration is set by how many images it holds. A
        // batch that outlives max.poll.interval.ms (300s) gets the pod evicted mid-batch, and that
        // is not a clean retry: the evicted pod loses the offsets for work it already did, and the
        // partition lands on a pod whose sidecar is just as busy and redoes the same images, so
        // offered load rises while throughput falls. Set here rather than as a deployment value so
        // the bound cannot drift away from the design that needs it.
        fetchBatchSize: config.SESSION_RECORDING_ML_IMAGE_SCRUB_BATCH_SIZE,
    }
}

export class IngestionSessionReplayMlImageScrubServer implements NodeServer {
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

        const s3Client = requireS3Client(buildSessionRecordingS3Client(this.config))
        const store = new ImageShardStore(
            s3Client,
            this.config.SESSION_RECORDING_V2_S3_BUCKET,
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_PREFIX,
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_S3_WRITE_TIMEOUT_MS
        )
        // The lane's own producer slot, not the generic one. It is on the replay cluster that holds
        // the source topic and carries this lane's message.max.bytes, and a parked image is an
        // original of the same size as the source message. The generic slot points at a different
        // cluster with librdkafka's 1 MB default, where every park of a normal image would fail
        // non-retriably.
        const dlqTopic = this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC
        let deadLetters: KafkaDeadLetterSink | null = null
        if (dlqTopic) {
            this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
            deadLetters = new KafkaDeadLetterSink(
                this.producerRegistry.getProducer(INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER),
                dlqTopic
            )
        }
        // Built after, because whether a dead-letter destination exists changes what the client does
        // with an image it cannot get scrubbed: park it, or keep waiting on it forever. Clearing the
        // topic is therefore the rollback, and it reverts to the documented waiting behaviour rather
        // than to producing at an empty topic name.
        const scrubClient = new ScrubClient(
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_SIDECAR_URL,
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS,
            deadLetters !== null
        )

        const maximumRecordBytes = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES + 64 * 1024
        const consumer = new KafkaConsumer(buildImageScrubConsumerConfig(this.config), {
            'fetch.message.max.bytes': maximumRecordBytes,
            'max.partition.fetch.bytes': maximumRecordBytes,
        })
        const batcher = new ImageBatcher(
            store,
            consumer,
            scrubClient,
            {
                flushIntervalMs: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_FLUSH_INTERVAL_MS,
                maxImages: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_IMAGES,
                maxBytes: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BYTES,
                scrubConcurrency: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_CONCURRENCY,
                dedupMaxRefs: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_DEDUP_MAX_REFS,
            },
            Date.now(),
            deadLetters
        )
        await scrubClient.waitUntilReachable()
        await consumer.connect((messages) => {
            const heartbeat = setInterval(() => consumer.heartbeat(), BATCH_HEARTBEAT_INTERVAL_MS)
            return batcher.handleBatch(messages, Date.now()).finally(() => clearInterval(heartbeat))
        })

        this.lifecycle.services.push({
            id: 'session-replay-ml-image-scrub',
            // batcher.stop() first: disconnect() waits on the running batch, and a batch waiting on an
            // unresponsive sidecar never returns, so without the interrupt a graceful stop runs to the
            // termination grace period and ends in a SIGKILL. Then disconnect() stops the poll loop and
            // commits stored offsets. The un-flushed buffer's offsets were never stored, so those
            // messages just replay on restart — a final flush here would only race the still-running
            // loop over the shared buffer.
            onShutdown: async () => {
                batcher.stop()
                await consumer.disconnect()
            },
            healthcheck: () => consumer.isHealthy(),
        })
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            additionalCleanup: () => this.producerRegistry?.disconnectAll(),
            redisPools: [],
        }
    }
}
