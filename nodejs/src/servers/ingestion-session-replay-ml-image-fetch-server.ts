import { DynamoDBClient } from '@aws-sdk/client-dynamodb'
import { NodeHttpHandler } from '@smithy/node-http-handler'

import { initializePrometheusLabels } from '~/common/api/router'
import {
    KAFKA_SESSION_REPLAY_IMAGE_FETCH,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1H,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1M,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_10M,
} from '~/common/config/kafka-topics'
import { KafkaConsumer, KafkaConsumerConfig } from '~/common/kafka/consumer/consumer-v1'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { SessionReplayProducerName } from '~/ingestion/pipelines/sessionreplay/config'
import {
    CrawlHistory,
    CrawlHistoryStore,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/crawl-history'
import { DynamoDBCrawlHistory } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/dynamodb-crawl-history'
import { FetchRunner } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/fetch-runner'
import { FrontierPublisher } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/frontier-publisher'
import { HostBudget } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/host-budget'
import { HttpImageFetcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/image-fetcher'
import { assertUrlPolicyLoaded } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/politeness-key'
import { UrlFetchConsumer } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/url-fetch-consumer'
import { createWebBotAuthRequestSigner } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/web-bot-auth'
import { resolveMlMirrorRedisConnection } from '~/ingestion/pipelines/sessionreplay/ml-mirror/config'
import { createProducerRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/producer-registry'
import { INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER } from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'

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
 * The poll interval binds rather than the health check, because the heartbeat above keeps the health
 * check satisfied through a long batch. A batch that passes the poll interval loses the partition
 * mid-batch to a pod that will be just as slow, so the lane sheds the rest of the batch instead.
 */
const STORE_BATCH_BUDGET_MS = 50_000

/** Matches MAX_URL_LEN in the crate, which is what the collector applied to the first candidate. */
const MAX_REDIRECT_URL_LENGTH = 2048

/** The addon holds a 15 MB native library and `index.ts` imports every server, so it loads on first use. */
let anonymizer: typeof import('@posthog/replay-anonymizer') | undefined
function getAnonymizer(): typeof import('@posthog/replay-anonymizer') {
    if (!anonymizer) {
        anonymizer = require('@posthog/replay-anonymizer') as typeof import('@posthog/replay-anonymizer')
        if (typeof anonymizer.isPublicHost !== 'function') {
            throw new Error('the replay-anonymizer addon has no isPublicHost: rebuild index.node')
        }
    }
    return anonymizer
}

export function buildFrontierPublisher(producer: KafkaProducerWrapper): FrontierPublisher {
    return new FrontierPublisher(producer, {
        frontierTopic: KAFKA_SESSION_REPLAY_IMAGE_FETCH,
        delayTiers: [
            { topic: KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1M, delayMs: 60_000 },
            { topic: KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_10M, delayMs: 600_000 },
            { topic: KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1H, delayMs: 3_600_000 },
        ],
    })
}

export function buildFetchRunner(
    config: IngestionSessionReplayMlMirrorServerConfig,
    publisher: FrontierPublisher
): FetchRunner {
    const webBotAuthSigner = createWebBotAuthRequestSigner(config.WEB_BOT_AUTH_PRIVATE_KEYS)
    const budget = new HostBudget({
        requestsPerSecond: config.SESSION_RECORDING_ML_IMAGE_FETCH_REQUESTS_PER_SECOND,
        burst: config.SESSION_RECORDING_ML_IMAGE_FETCH_BURST,
        maxConcurrent: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_DOMAIN,
        breakerFailures: config.SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_FAILURES,
        breakerCooldownMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_COOLDOWN_MS,
        breakerMaxCooldownMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_MAX_COOLDOWN_MS,
        maxTrackedDomains: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_DOMAINS,
    })
    return new FetchRunner(
        new HttpImageFetcher(
            {
                maxUrlLength: MAX_REDIRECT_URL_LENGTH,
                // The crate's rule, so a redirect target meets the check the collector already applied
                // to the first candidate rather than a second answer to the same question.
                isPublicHost: (host) => getAnonymizer().isPublicHost(host),
            },
            webBotAuthSigner
        ),
        budget,
        {
            maxConcurrentPerDomain: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_DOMAIN,
            maxInFlightRequests: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS,
            batchBudgetMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_BUDGET_MS,
            maxBytes: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES,
            requestTimeoutMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS,
            maxRedirects: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_REDIRECTS,
            defaultRetryAfterMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_DEFAULT_RETRY_AFTER_MS,
        },
        publisher
    )
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
 */
export class IngestionSessionReplayMlImageFetchServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionSessionReplayMlMirrorServerConfig
    private crawlHistoryPool?: RedisPool
    private crawlHistoryClient?: DynamoDBClient
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
        // Here rather than on the first record. The parser calls into this addon for every URL, and
        // it must answer with a reason rather than raise, so a build that shipped without the addon
        // has to stop the pod at startup instead.
        assertUrlPolicyLoaded()

        const dryRun = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN
        if (!dryRun) {
            throw new Error(
                'SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN cannot be cleared yet: this lane obeys no robots.txt and produces no images'
            )
        }

        let crawlHistory: CrawlHistoryStore
        let crawlHistoryTtlSeconds: number
        const tableName = this.config.AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TABLE
        if (tableName) {
            const dynamoDBTimeoutMs = this.config.AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS
            if (!Number.isFinite(dynamoDBTimeoutMs) || dynamoDBTimeoutMs <= 0) {
                throw new Error(
                    `AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS must be a positive number, got ${dynamoDBTimeoutMs}`
                )
            }
            this.crawlHistoryClient = new DynamoDBClient({
                region: this.config.SESSION_RECORDING_V2_S3_REGION || 'us-east-1',
                endpoint: this.config.SESSION_RECORDING_DYNAMODB_ENDPOINT,
                maxAttempts: 5,
                requestHandler: new NodeHttpHandler(),
            })
            const dynamoDBCrawlHistory = new DynamoDBCrawlHistory(
                this.crawlHistoryClient,
                tableName,
                dynamoDBTimeoutMs,
                STORE_BATCH_BUDGET_MS
            )
            await dynamoDBCrawlHistory.validateAccess(Date.now())
            crawlHistory = dynamoDBCrawlHistory
            crawlHistoryTtlSeconds = this.config.AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS
        } else {
            const connection = resolveMlMirrorRedisConnection(this.config)
            if (!connection) {
                throw new Error('SESSION_RECORDING_ML_REDIS_HOST must be set for the image-fetch consumer')
            }
            const redisTimeoutMs = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_REDIS_TIMEOUT_MS
            this.crawlHistoryPool = createRedisPoolFromConfig({
                connection: { ...connection, options: { ...connection.options, commandTimeout: redisTimeoutMs } },
                poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
                poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
                acquireTimeoutMillis: redisTimeoutMs,
            })
            crawlHistory = new CrawlHistory(this.crawlHistoryPool, redisTimeoutMs, STORE_BATCH_BUDGET_MS)
            crawlHistoryTtlSeconds = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_SEEN_TTL_SECONDS
        }

        // Built even in dry run, so the wiring is exercised by every start rather than only by the
        // one that clears the flag.
        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const publisher = buildFrontierPublisher(
            this.producerRegistry.getProducer(INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER)
        )

        const fetchConsumer = new UrlFetchConsumer(
            crawlHistory,
            publisher,
            {
                maxAgeMs: this.config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_AGE_MS,
                dedupMaxRefs: this.config.SESSION_RECORDING_ML_IMAGE_FETCH_DEDUP_MAX_REFS,
                seenTtlSeconds: crawlHistoryTtlSeconds,
                dryRun,
            },
            dryRun ? undefined : buildFetchRunner(this.config, publisher)
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
            redisPools: this.crawlHistoryPool ? [this.crawlHistoryPool] : [],
            additionalCleanup: async () => {
                this.crawlHistoryClient?.destroy()
                await this.producerRegistry?.disconnectAll()
            },
        }
    }
}
