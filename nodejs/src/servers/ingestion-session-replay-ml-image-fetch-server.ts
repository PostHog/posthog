import { DynamoDBClient } from '@aws-sdk/client-dynamodb'
import { NodeHttpHandler } from '@smithy/node-http-handler'

import { initializePrometheusLabels } from '~/common/api/router'
import {
    KAFKA_SESSION_REPLAY_IMAGE_FETCH,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1H,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1M,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_10M,
    KAFKA_SESSION_REPLAY_IMAGE_SCRUB,
} from '~/common/config/kafka-topics'
import { KafkaConsumerV2, KafkaConsumerV2Config, RdKafkaConsumerOverrides } from '~/common/kafka/consumer/consumer-v2'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { logger } from '~/common/utils/logger'
import { SessionReplayProducerName } from '~/ingestion/pipelines/sessionreplay/config'
import {
    ConfigurationPolicyService,
    HttpConfigurationFetcher,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/configuration-policy'
import { DynamoDBCrawlHistory } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/dynamodb-crawl-history'
import { FetchRunner } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/fetch-runner'
import { KafkaFrontierDeadLetterSink } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/frontier-dead-letter-sink'
import { FrontierPublisher } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/frontier-publisher'
import { HostBudget } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/host-budget'
import {
    ImageFetchBatchJoiner,
    assertImageFetchBatchTarget,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/image-fetch-batch-joiner'
import { HttpImageFetcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/image-fetcher'
import { OriginRequestScheduler } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/origin-request-scheduler'
import { assertUrlPolicyLoaded } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/politeness-key'
import { UrlFetchConsumer } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/url-fetch-consumer'
import { createWebBotAuthRequestSigner } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/web-bot-auth'
import { createProducerRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/producer-registry'
import { INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER } from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'
import { HealthCheckResultOk } from '~/types'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import {
    IngestionSessionReplayMlMirrorServerConfig,
    buildMlMirrorServerConfig,
} from './ingestion-session-replay-ml-mirror-server'

/**
 * How long the store may spend on one batch, well inside Kafka's max.poll.interval.ms of 300s.
 *
 * The poll interval binds rather than the health check, because the heartbeat above keeps the health
 * check satisfied through a long batch. A batch that passes the poll interval loses the partition
 * mid-batch to a pod that will be just as slow, so the lane sheds the rest of the batch instead.
 */
const STORE_BATCH_BUDGET_MS = 50_000
const IMAGE_FETCH_KAFKA_QUEUE_BUDGET_KBYTES = 102_400

/** Matches MAX_URL_LEN in the crate, which is what the collector applied to the first candidate. */
const MAX_REDIRECT_URL_LENGTH = 2048

const BLOCKED_IMAGE_FETCH_DEAD_LETTER_TOPICS = [
    KAFKA_SESSION_REPLAY_IMAGE_FETCH,
    KAFKA_SESSION_REPLAY_IMAGE_SCRUB,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1M,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_10M,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1H,
]

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

export function buildFrontierPublisher(
    producer: KafkaProducerWrapper,
    maxConcurrentImagePublishes: number
): FrontierPublisher {
    return new FrontierPublisher(producer, {
        frontierTopic: KAFKA_SESSION_REPLAY_IMAGE_FETCH,
        scrubTopic: KAFKA_SESSION_REPLAY_IMAGE_SCRUB,
        delayTiers: [
            { topic: KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1M, delayMs: 60_000, metricTopic: 'retry_1m' },
            { topic: KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_10M, delayMs: 600_000, metricTopic: 'retry_10m' },
            { topic: KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1H, delayMs: 3_600_000, metricTopic: 'retry_1h' },
        ],
        maxConcurrentImagePublishes,
        maxConcurrentRepublishes: maxConcurrentImagePublishes,
    })
}

export function buildFetchRunner(
    config: IngestionSessionReplayMlMirrorServerConfig,
    publisher: FrontierPublisher
): FetchRunner {
    const webBotAuthSigner = createWebBotAuthRequestSigner(config.WEB_BOT_AUTH_PRIVATE_KEYS)
    const budget = new HostBudget({
        requestsPerSecond: config.SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_REQUESTS_PER_SECOND,
        burst: config.SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BURST,
        maxConcurrent: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_REGISTRABLE_DOMAIN,
        breakerFailures: config.SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_FAILURES,
        breakerCooldownMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_COOLDOWN_MS,
        breakerMaxCooldownMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_MAX_COOLDOWN_MS,
        maxTrackedRegistrableDomains: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_REGISTRABLE_DOMAINS,
        maxTrackedOrigins: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_ORIGINS,
    })
    const scheduler = new OriginRequestScheduler(budget, config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS)
    const configurationPolicy = new ConfigurationPolicyService(
        new HttpConfigurationFetcher(
            webBotAuthSigner,
            scheduler,
            config.SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS
        )
    )
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
        scheduler,
        configurationPolicy,
        {
            maxConcurrentPerRegistrableDomain:
                config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_REGISTRABLE_DOMAIN,
            maxInFlightRequests: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS,
            lowOriginDiversityMinimumRequestSlots:
                config.SESSION_RECORDING_ML_IMAGE_FETCH_LOW_ORIGIN_DIVERSITY_MINIMUM_REQUEST_SLOTS,
            lowOriginDiversityRepublishThreshold:
                config.SESSION_RECORDING_ML_IMAGE_FETCH_LOW_ORIGIN_DIVERSITY_REPUBLISH_THRESHOLD,
            lowOriginDiversityProgress: config.SESSION_RECORDING_ML_IMAGE_FETCH_LOW_ORIGIN_DIVERSITY_PROGRESS,
            batchBudgetMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_BUDGET_MS,
            maxBytes: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES,
            requestTimeoutMs: config.SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS,
            maxRedirects: config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_REDIRECTS,
            seenTtlSeconds: config.AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS,
        },
        publisher
    )
}

export function buildImageFetchConsumerConfigs(
    config: IngestionSessionReplayMlMirrorServerConfig
): KafkaConsumerV2Config[] {
    const targetBatchCount = config.SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH
    assertImageFetchBatchTarget(targetBatchCount)
    return Array.from({ length: targetBatchCount }, () => ({
        topic: KAFKA_SESSION_REPLAY_IMAGE_FETCH,
        groupId: config.SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID,
        autoCommit: true,
        autoOffsetStore: true,
        fetchBatchSize: config.SESSION_RECORDING_ML_IMAGE_FETCH_BATCH_SIZE,
    }))
}

export function buildImageFetchConsumerOverrides(
    config: IngestionSessionReplayMlMirrorServerConfig,
    consumerCount: number
): RdKafkaConsumerOverrides {
    assertImageFetchBatchTarget(consumerCount)
    const maximumRecordBytes = config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES + 64 * 1024
    return {
        'fetch.message.max.bytes': maximumRecordBytes,
        'max.partition.fetch.bytes': maximumRecordBytes,
        'queued.max.messages.kbytes': Math.floor(IMAGE_FETCH_KAFKA_QUEUE_BUDGET_KBYTES / consumerCount),
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

        const tableName = this.config.AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TABLE
        if (!tableName) {
            throw new Error('AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TABLE must be set for the image-fetch consumer')
        }
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
        const crawlHistory = new DynamoDBCrawlHistory(
            this.crawlHistoryClient,
            tableName,
            dynamoDBTimeoutMs,
            STORE_BATCH_BUDGET_MS
        )
        await crawlHistory.validateAccess(Date.now())

        // Built even in dry run, so the wiring is exercised by every start rather than only by the
        // one that clears the flag.
        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const producer = this.producerRegistry.getProducer(INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER)
        const publisher = buildFrontierPublisher(
            producer,
            this.config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_PENDING_PUBLISHES
        )
        const deadLetterTopic = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_DLQ_TOPIC
        const deadLetters = deadLetterTopic
            ? new KafkaFrontierDeadLetterSink(producer, deadLetterTopic, BLOCKED_IMAGE_FETCH_DEAD_LETTER_TOPICS)
            : null

        const fetchConsumer = new UrlFetchConsumer(
            crawlHistory,
            publisher,
            {
                seenTtlSeconds: this.config.AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS,
                dryRun,
            },
            buildFetchRunner(this.config, publisher),
            deadLetters
        )
        logger.info('🌐', 'ml_image_fetch_started', { dryRun })

        const consumerConfigs = buildImageFetchConsumerConfigs(this.config)
        const batchJoiner = new ImageFetchBatchJoiner(consumerConfigs.length, (messages) =>
            fetchConsumer.handleBatch(messages, Date.now())
        )
        const consumerOverrides = buildImageFetchConsumerOverrides(this.config, consumerConfigs.length)
        const consumers = consumerConfigs.map(
            (consumerConfig) => new KafkaConsumerV2(consumerConfig, consumerOverrides)
        )

        this.lifecycle.services.push({
            id: 'session-replay-ml-image-fetch',
            onShutdown: async () => {
                await Promise.all(consumers.map((consumer) => consumer.disconnect()))
            },
            healthcheck: () => {
                for (const consumer of consumers) {
                    const health = consumer.isHealthy()
                    if (health.isError()) {
                        return health
                    }
                }
                return new HealthCheckResultOk()
            },
        })
        await Promise.all(
            consumers.map((consumer) => consumer.connect((messages) => batchJoiner.handleBatch(messages)))
        )
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [],
            additionalCleanup: async () => {
                this.crawlHistoryClient?.destroy()
                await this.producerRegistry?.disconnectAll()
            },
        }
    }
}
