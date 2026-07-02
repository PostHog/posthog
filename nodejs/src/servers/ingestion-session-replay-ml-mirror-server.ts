import { GetObjectCommand, S3Client } from '@aws-sdk/client-s3'

import { initializePrometheusLabels } from '~/common/api/router'
import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { getDefaultKafkaDownstreamProducerEnvConfig } from '~/ingestion/common/outputs/producers'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import { AllowListFetcher, loadAllowLists } from '~/ingestion/pipelines/sessionreplay/anonymize/allow-list-loader'
import { ScrubContext } from '~/ingestion/pipelines/sessionreplay/anonymize/config'
import {
    type SessionReplayProducerName,
    getDefaultSessionRecordingApiConfig,
    getDefaultSessionRecordingConfig,
    getDefaultSessionReplayOutputsConfig,
} from '~/ingestion/pipelines/sessionreplay/config'
import {
    SessionRecordingIngester,
    SessionRecordingIngesterCollaborators,
} from '~/ingestion/pipelines/sessionreplay/consumer'
import { MlMirrorConfig, getDefaultMlMirrorConfig } from '~/ingestion/pipelines/sessionreplay/ml-mirror/config'
import { MlBlockMetadataSink } from '~/ingestion/pipelines/sessionreplay/ml-mirror/ml-block-metadata-sink'
import { createMlMirrorReplayPipeline } from '~/ingestion/pipelines/sessionreplay/ml-mirror/ml-mirror-pipeline'
import { resolvePseudonymKey } from '~/ingestion/pipelines/sessionreplay/ml-mirror/pseudonym-key'
import { createProducerRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/producer-registry'
import { createOutputsRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/registry'
import { BlackholeSessionBatchFileStorage } from '~/ingestion/pipelines/sessionreplay/sessions/blackhole-session-batch-writer'
import { S3SessionBatchFileStorage } from '~/ingestion/pipelines/sessionreplay/sessions/s3-session-batch-writer'
import { SessionConsoleLogStore } from '~/ingestion/pipelines/sessionreplay/sessions/session-console-log-store'
import { CleartextRecordingEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/crypto/cleartext-encryptor'
import { SessionFeatureStore } from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { CleartextKeyStore } from '~/ingestion/pipelines/sessionreplay/shared/keystore/cleartext-keystore'
import { getDefaultKafkaSessionreplayProducerEnvConfig } from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'
import { buildSessionRecordingS3Client } from '~/ingestion/pipelines/sessionreplay/shared/s3-client'

import { RedisPool } from '../types'
import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import { IngestionSessionReplayServerConfig, buildSessionReplayRedisPools } from './ingestion-session-replay-server'

/** Full config for an ML mirror deployment: the primary replay config plus ML knobs. */
export type IngestionSessionReplayMlMirrorServerConfig = IngestionSessionReplayServerConfig & MlMirrorConfig

/** Assembles the ML-mirror config; shared by the mirror ingester and the Parquet-sink deployments. */
export function buildMlMirrorServerConfig(
    config: Partial<IngestionSessionReplayMlMirrorServerConfig>
): IngestionSessionReplayMlMirrorServerConfig {
    return {
        ...defaultConfig,
        ...overrideConfigWithEnv(getDefaultIngestionConsumerConfig()),
        ...overrideConfigWithEnv(getDefaultKafkaDownstreamProducerEnvConfig()),
        ...overrideConfigWithEnv(getDefaultKafkaSessionreplayProducerEnvConfig()),
        ...overrideConfigWithEnv({
            ...getDefaultSessionRecordingConfig(),
            // Distinct default group id so the mirror gets its own copy of every recording rather than
            // splitting the snapshot topic's partitions with the primary ingester (still env-overridable).
            INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID: 'session-replay-ml-mirror',
        }),
        ...overrideConfigWithEnv(getDefaultSessionRecordingApiConfig()),
        ...overrideConfigWithEnv(getDefaultSessionReplayOutputsConfig()),
        ...overrideConfigWithEnv(getDefaultMlMirrorConfig()),
        ...config,
    }
}

export class IngestionSessionReplayMlMirrorServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionSessionReplayMlMirrorServerConfig

    private postgres?: PostgresRouter
    private producerRegistry?: KafkaProducerRegistry<SessionReplayProducerName>
    private redisPool?: RedisPool
    private restrictionRedisPool?: RedisPool

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

        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const outputs = createOutputsRegistry().build(this.producerRegistry, this.config)

        const pools = buildSessionReplayRedisPools(this.config)
        this.redisPool = pools.redisPool
        this.restrictionRedisPool = pools.restrictionRedisPool

        const s3Client = buildSessionRecordingS3Client(this.config)
        const bucket = this.config.SESSION_RECORDING_V2_S3_BUCKET
        const prefix = this.config.SESSION_RECORDING_V2_S3_PREFIX

        const pseudonymSecret = await resolvePseudonymKey(this.config)

        // Anonymized blocks are written unencrypted, in a single prefix (no retention sharding).
        const fileStorage = s3Client
            ? new S3SessionBatchFileStorage(s3Client, bucket, prefix, this.config.SESSION_RECORDING_V2_S3_TIMEOUT_MS)
            : new BlackholeSessionBatchFileStorage()

        const allow = await loadAllowLists(this.buildAllowListFetcher(s3Client, bucket))
        const useRustAnonymizer = this.config.SESSION_RECORDING_ML_RUST_ANONYMIZER
        if (useRustAnonymizer) {
            // Lazy require so the native addon is only loaded (and only needs to ship) when the flag is
            // on; the addon holds its own copy of the immutable allow lists, set once at startup.
            const { initAnonymizer } =
                require('@posthog/replay-anonymizer') as typeof import('@posthog/replay-anonymizer')
            initAnonymizer(allow.entries())
            logger.info('🦀', 'ml_mirror_rust_anonymizer_enabled')
        }
        const scrubContext: ScrubContext = { allow, useRustAnonymizer }

        // Block metadata is produced to Kafka; the dedicated Parquet-sink deployment writes it to the ML bucket.
        const metadataStore = new MlBlockMetadataSink(outputs, pseudonymSecret)

        // Cleartext crypto: no encryption, deletions not honored (every session stays cleartext).
        const keyStore = new CleartextKeyStore()
        const collaborators: SessionRecordingIngesterCollaborators = {
            fileStorage,
            metadataStore,
            // Console logs and ML features are not mirrored.
            consoleLogStore: new SessionConsoleLogStore(outputs, {
                messageLimit: this.config.SESSION_RECORDING_V2_CONSOLE_LOG_STORE_SYNC_BATCH_LIMIT,
                enabled: false,
            }),
            featureStore: new SessionFeatureStore(outputs, false),
            keyStore,
            encryptor: new CleartextRecordingEncryptor(keyStore),
            createPipeline: (pipelineConfig) => createMlMirrorReplayPipeline({ ...pipelineConfig, scrubContext }),
        }

        const ingester = new SessionRecordingIngester(
            this.config,
            this.postgres,
            outputs,
            this.redisPool,
            this.restrictionRedisPool,
            collaborators
        )
        await ingester.start()
        this.lifecycle.services.push(ingester.service)
    }

    private buildAllowListFetcher(s3Client: S3Client | null, bucket: string): AllowListFetcher | undefined {
        const key = this.config.SESSION_RECORDING_ML_ALLOW_LIST_S3_KEY
        if (!s3Client || !key) {
            return undefined
        }
        return async () => {
            const response = await s3Client.send(new GetObjectCommand({ Bucket: bucket, Key: key }))
            const body = await response.Body?.transformToString()
            return body ? parseJSON(body) : {}
        }
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [this.redisPool, this.restrictionRedisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
            additionalCleanup: async () => {
                await this.producerRegistry?.disconnectAll()
            },
        }
    }
}
