import { initializePrometheusLabels } from '~/common/api/router'
import { KAFKA_SESSION_REPLAY_IMAGE_FETCH } from '~/common/config/kafka-topics'
import { KafkaConsumer, KafkaConsumerConfig } from '~/common/kafka/consumer/consumer-v1'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { FetchRunner } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/fetch-runner'
import { HostBudget } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/host-budget'
import { HttpImageFetcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/image-fetcher'
import { UrlFetchConsumer } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/url-fetch-consumer'
import { UrlSightings } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/url-sightings'
import { resolveMlMirrorRedisConnection } from '~/ingestion/pipelines/sessionreplay/ml-mirror/config'

import { RedisPool } from '../types'
import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import {
    IngestionSessionReplayMlMirrorServerConfig,
    buildMlMirrorServerConfig,
} from './ingestion-session-replay-ml-mirror-server'

// The poll loop only heartbeats between batches, so a slow batch is refreshed from inside it. Must
// stay under CONSUMER_MAX_HEARTBEAT_INTERVAL_MS (30s), which binds long before max.poll.interval.ms.
const BATCH_HEARTBEAT_INTERVAL_MS = 10_000

/**
 * How long the store may spend on one batch, well inside Kafka's max.poll.interval.ms of 300s.
 *
 * That is the bound that matters rather than the health check, because the heartbeat above keeps the
 * health check satisfied through a long batch. A batch that passes the poll interval gets the
 * partition revoked mid-batch and replayed by a pod that will be just as slow, so the lane sheds the
 * rest of a batch instead.
 */
const STORE_BATCH_BUDGET_MS = 50_000

export function buildFetchRunner(config: IngestionSessionReplayMlMirrorServerConfig): FetchRunner {
    const budget = new HostBudget({
        requestsPerSecond: config.SESSION_RECORDING_ML_IMAGE_FETCH_REQUESTS_PER_SECOND,
        burst: config.SESSION_RECORDING_ML_IMAGE_FETCH_BURST,
        maxConcurrent: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_DOMAIN,
        breakerFailures: config.SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_FAILURES,
        breakerCooldownMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_COOLDOWN_MS,
        breakerMaxCooldownMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_MAX_COOLDOWN_MS,
        maxTrackedDomains: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_DOMAINS,
    })
    return new FetchRunner(new HttpImageFetcher(), budget, {
        maxConcurrentPerDomain: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_DOMAIN,
        maxConcurrentDomains: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_DOMAINS,
        batchBudgetMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_BUDGET_MS,
        maxBytes: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES,
        requestTimeoutMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS,
        maxRedirects: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_REDIRECTS,
        defaultRetryAfterMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_DEFAULT_RETRY_AFTER_MS,
    })
}

export function buildImageFetchConsumerConfig(config: IngestionSessionReplayMlMirrorServerConfig): KafkaConsumerConfig {
    return {
        topic: KAFKA_SESSION_REPLAY_IMAGE_FETCH,
        groupId: config.SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID,
        autoCommit: true,
        autoOffsetStore: true,
        fetchBatchSize: config.SESSION_RECORDING_ML_IMAGE_FETCH_BATCH_SIZE,
    }
}

/**
 * The image fetch lane.
 *
 * It has its own deployment because it waits on network IO and wants many small pods, where the
 * scrub sidecar it feeds uses CPU and ML models and wants few large ones.
 *
 * The lane starts in dry run and sends no request. See
 * `SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN`.
 */
export class IngestionSessionReplayMlImageFetchServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionSessionReplayMlMirrorServerConfig
    private sightingPool?: RedisPool

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

        // Before anything connects. The request path exists, but this lane reads no robots.txt and
        // produces nothing to the scrub topic, so fetching now would be rude and would throw the
        // images away.
        const dryRun = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN
        if (!dryRun) {
            throw new Error(
                'SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN cannot be cleared yet: this lane obeys no robots.txt and produces no images'
            )
        }

        // The ml-mirror's instance, which is deliberately not the cluster that serves the primary
        // replay lane: this store holds one key per distinct image URL, and its eviction pressure
        // must not be able to reach the lane that gates replay ingestion.
        const connection = resolveMlMirrorRedisConnection(this.config)
        if (!connection) {
            throw new Error('SESSION_RECORDING_ML_REDIS_HOST must be set for the image-fetch consumer')
        }
        const redisTimeoutMs = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_REDIS_TIMEOUT_MS
        this.sightingPool = createRedisPoolFromConfig({
            // The lane's own command timeout, not the mirror's 200ms: one round trip here carries a
            // whole chunk of keys rather than a single per-session command.
            connection: { ...connection, options: { ...connection.options, commandTimeout: redisTimeoutMs } },
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
            acquireTimeoutMillis: redisTimeoutMs,
        })
        const sightings = new UrlSightings(this.sightingPool, redisTimeoutMs, STORE_BATCH_BUDGET_MS)

        const fetchConsumer = new UrlFetchConsumer(
            sightings,
            {
                maxAgeMs: this.config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_AGE_MS,
                dedupMaxRefs: this.config.SESSION_RECORDING_ML_IMAGE_FETCH_DEDUP_MAX_REFS,
                dryRun,
            },
            dryRun ? undefined : buildFetchRunner(this.config)
        )
        logger.info('🌐', 'ml_image_fetch_started', { dryRun })

        const consumer = new KafkaConsumer(buildImageFetchConsumerConfig(this.config))
        await consumer.connect((messages) => {
            const heartbeat = setInterval(() => consumer.heartbeat(), BATCH_HEARTBEAT_INTERVAL_MS)
            return fetchConsumer.handleBatch(messages, Date.now()).finally(() => clearInterval(heartbeat))
        })

        this.lifecycle.services.push({
            id: 'session-replay-ml-image-fetch',
            onShutdown: () => consumer.disconnect(),
            healthcheck: () => consumer.isHealthy(),
        })
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: this.sightingPool ? [this.sightingPool] : [],
        }
    }
}
