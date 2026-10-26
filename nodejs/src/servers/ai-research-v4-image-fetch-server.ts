import { DynamoDBClient } from '@aws-sdk/client-dynamodb'
import { KMSClient } from '@aws-sdk/client-kms'
import { NodeHttpHandler } from '@smithy/node-http-handler'
import { LibrdKafkaError } from 'node-rdkafka'

import { KafkaConsumer, KafkaConsumerConfig, findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'
import {
    EachBatch,
    KafkaConsumerV2,
    KafkaConsumerV2Config,
    RdKafkaConsumerOverrides,
} from '~/common/kafka/consumer/consumer-v2'
import { KafkaProducer } from '~/common/kafka/producer'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { logger } from '~/common/utils/logger'
import { TopHog } from '~/ingestion/framework/tophog/tophog'
import { AiResearchV4ServerConfig } from '~/ingestion/pipelines/sessionreplay/ai-research/config'
import {
    ConfigurationPolicyService,
    HttpConfigurationFetcher,
} from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/configuration-policy'
import { DynamoDBCrawlHistory } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/dynamodb-crawl-history'
import { FetchCandidatePool } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/fetch-candidate-pool'
import { FetchRunner } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/fetch-runner'
import { KafkaFrontierDeadLetterSink } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/frontier-dead-letter-sink'
import { FrontierPublisher } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/frontier-publisher'
import { HostBudget } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/host-budget'
import {
    ImageFetchBatchJoiner,
    assertImageFetchBatchTarget,
} from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/image-fetch-batch-joiner'
import { HttpImageFetcher } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/image-fetcher'
import type { RefreshingImageSink } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/image-sink'
import { V4JobAdmission } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/job-admission'
import {
    BLOCKED_IMAGE_FETCH_DEAD_LETTER_TOPICS,
    HostLimits,
    V4_IMAGE_FETCH_DELAY_TOPICS,
    V4_IMAGE_FETCH_LANE,
    assertOwnImageFetchGroup,
    v4HostLimits,
} from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/lane'
import { OriginRequestScheduler } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/origin-request-scheduler'
import { assertUrlPolicyLoaded } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/politeness-key'
import { createPoolWindowBatchHandler } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/pool-window-batch-handler'
import {
    AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER,
    AiResearchV4ImageFetchProducerName,
    createV4ImageFetchOutputs,
    createV4ImageFetchProducerRegistry,
} from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/producer'
import { RawImageStore } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/raw-image-store'
import { TeamMonthResponseUrlBinder } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/response-url-binding'
import { RetryDelayConsumer } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/retry-delay-consumer'
import { SharedImageFetcher } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/shared-image-fetcher'
import { ImageFetchTopHogMetrics } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/tophog-metrics'
import { UrlFetchConsumer } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/url-fetch-consumer'
import { createWebBotAuthRequestSigner } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/web-bot-auth'
import { AiResearchV4ConsumerServer } from '~/ingestion/pipelines/sessionreplay/ai-research/server/v4-consumer-server'
import { TeamMonthKeys } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-month-keys'
import { CaptureWatermark, capturedRecords } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'
import { buildSessionRecordingS3Client } from '~/ingestion/pipelines/sessionreplay/shared/s3-client'
import { HealthCheckResultOk } from '~/types'

import { CleanupResources } from './base-server'

/**
 * How long the store may spend on one batch, well inside Kafka's max.poll.interval.ms of 300s.
 *
 * The poll interval binds rather than the health check, because the heartbeat above keeps the health
 * check satisfied through a long batch. A batch that passes the poll interval loses the partition
 * mid-batch to a pod that will be just as slow, so the lane sheds the rest of the batch instead.
 */
const STORE_BATCH_BUDGET_MS = 50_000
const IMAGE_FETCH_KAFKA_QUEUE_BUDGET_KBYTES = 102_400
const IMAGE_FETCH_MIN_CONSUMER_QUEUE_KBYTES = 25_600
/**
 * The pool window paces a member in continuous-pool mode. This limit stays above that window at typical
 * batch sizes, and it is the hard bound on a member's resident URLs and crash replay when batches are large.
 */
const POOL_MAX_BATCHES_IN_FLIGHT_PER_MEMBER = 4

/** Matches MAX_URL_LEN in the crate, which is what the collector applied to the first candidate. */
const MAX_REDIRECT_URL_LENGTH = 2048

/**
 * Headroom on top of the sleeping a batch can do, for the publishing between the sleeps.
 *
 * librdkafka rejects a `max.poll.interval.ms` above one day, so a tier and a batch size whose
 * product passes that is a configuration error rather than something to clamp silently.
 */
const POLL_INTERVAL_MARGIN_MS = 60_000
const MAX_POLL_INTERVAL_MS = 86_400_000
const REVOKED_PARTITION_CODES = new Set([-172, -190, -142, -144])

/** The addon is a native library and `index.ts` imports every server, so it loads on first use. */
let urlPolicy: typeof import('@posthog/ai-research-v4-native') | undefined
function getUrlPolicy(): typeof import('@posthog/ai-research-v4-native') {
    if (!urlPolicy) {
        urlPolicy = require('@posthog/ai-research-v4-native') as typeof import('@posthog/ai-research-v4-native')
        if (typeof urlPolicy.isPublicHost !== 'function') {
            throw new Error('the ai-research-v4-native addon has no isPublicHost: rebuild index.node')
        }
    }
    return urlPolicy
}

export function buildFrontierPublisher(producer: KafkaProducer, maxConcurrentRepublishes: number): FrontierPublisher {
    return new FrontierPublisher(producer, {
        frontierTopic: V4_IMAGE_FETCH_LANE.frontier,
        delayTiers: [
            { topic: V4_IMAGE_FETCH_LANE.retry1m, delayMs: 60_000, metricTopic: 'retry_1m' },
            { topic: V4_IMAGE_FETCH_LANE.retry10m, delayMs: 600_000, metricTopic: 'retry_10m' },
            { topic: V4_IMAGE_FETCH_LANE.retry1h, delayMs: 3_600_000, metricTopic: 'retry_1h' },
        ],
        maxConcurrentRepublishes,
    })
}

/** The lane's per registrable domain limits: the configured share of the configured limits. */
export function imageFetchHostLimits(config: AiResearchV4ServerConfig): HostLimits {
    return v4HostLimits(
        {
            requestsPerSecond: config.AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_REQUESTS_PER_SECOND,
            burst: config.AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BURST,
            maxConcurrent: config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_CONCURRENT_PER_REGISTRABLE_DOMAIN,
        },
        config.AI_RESEARCH_V4_IMAGE_FETCH_HOST_BUDGET_SHARE
    )
}

export function buildFetchRunner(
    config: AiResearchV4ServerConfig,
    publisher: FrontierPublisher,
    topHogMetrics: ImageFetchTopHogMetrics,
    imageSink: RefreshingImageSink,
    keys: Pick<TeamMonthKeys, 'get'>,
    hostLimits: HostLimits = imageFetchHostLimits(config)
): FetchRunner {
    const webBotAuthSigner = createWebBotAuthRequestSigner(config.AI_RESEARCH_V4_IMAGE_FETCH_WEB_BOT_AUTH_PRIVATE_KEYS)
    const budget = new HostBudget({
        ...hostLimits,
        breakerFailures: config.AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_FAILURES,
        breakerCooldownMs: config.AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_COOLDOWN_MS,
        breakerMaxCooldownMs: config.AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_MAX_COOLDOWN_MS,
        maxTrackedRegistrableDomains: config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_TRACKED_REGISTRABLE_DOMAINS,
        maxTrackedOrigins: config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_TRACKED_ORIGINS,
    })
    const scheduler = new OriginRequestScheduler(
        budget,
        config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS,
        topHogMetrics
    )
    const configurationPolicy = new ConfigurationPolicyService(
        new HttpConfigurationFetcher(webBotAuthSigner, scheduler, config.AI_RESEARCH_V4_IMAGE_FETCH_REQUEST_TIMEOUT_MS)
    )
    return new FetchRunner(
        // The recorder sends one job per team for the same URL and month, so one fetch serves them all.
        new SharedImageFetcher(
            new HttpImageFetcher(
                {
                    maxUrlLength: MAX_REDIRECT_URL_LENGTH,
                    // The crate's rule, so a redirect target meets the check the collector already applied
                    // to the first candidate rather than a second answer to the same question.
                    isPublicHost: (host) => getUrlPolicy().isPublicHost(host),
                },
                webBotAuthSigner
            )
        ),
        budget,
        scheduler,
        configurationPolicy,
        {
            maxConcurrentPerRegistrableDomain: hostLimits.maxConcurrent,
            maxInFlightRequests: config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS,
            batchBudgetMs: config.AI_RESEARCH_V4_IMAGE_FETCH_REQUEST_BUDGET_MS,
            maxBytes: config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_IMAGE_BYTES,
            requestTimeoutMs: config.AI_RESEARCH_V4_IMAGE_FETCH_REQUEST_TIMEOUT_MS,
            maxRedirects: config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_REDIRECTS,
            seenTtlSeconds: config.AI_RESEARCH_V4_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS,
            continuousPool: config.AI_RESEARCH_V4_IMAGE_FETCH_CONTINUOUS_POOL
                ? {
                      refillRunnableUrls: config.AI_RESEARCH_V4_IMAGE_FETCH_POOL_REFILL_RUNNABLE_URLS,
                      maxQueuedUrlsPerOwner: config.AI_RESEARCH_V4_IMAGE_FETCH_POOL_MAX_QUEUED_URLS_PER_MEMBER,
                  }
                : undefined,
        },
        publisher,
        imageSink,
        new TeamMonthResponseUrlBinder(keys),
        topHogMetrics
    )
}

export function buildImageFetchConsumerConfigs(config: AiResearchV4ServerConfig): KafkaConsumerV2Config[] {
    assertOwnImageFetchGroup(config.AI_RESEARCH_V4_IMAGE_FETCH_GROUP_ID)
    const targetBatchCount = config.AI_RESEARCH_V4_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH
    assertImageFetchBatchTarget(targetBatchCount)
    return Array.from({ length: targetBatchCount }, () => ({
        topic: V4_IMAGE_FETCH_LANE.frontier,
        groupId: config.AI_RESEARCH_V4_IMAGE_FETCH_GROUP_ID,
        autoCommit: true,
        autoOffsetStore: true,
        fetchBatchSize: config.AI_RESEARCH_V4_IMAGE_FETCH_BATCH_SIZE,
        maxBackgroundTasks: config.AI_RESEARCH_V4_IMAGE_FETCH_CONTINUOUS_POOL
            ? POOL_MAX_BATCHES_IN_FLIGHT_PER_MEMBER
            : 2,
        backgroundTaskTimeoutMs: 240_000,
    }))
}

export function imageFetchBatchesPerPass(config: AiResearchV4ServerConfig, consumerCount: number): number {
    return config.AI_RESEARCH_V4_IMAGE_FETCH_JOIN_MEMBER_BATCHES ? consumerCount : 1
}

export function buildImageFetchConsumerOverrides(
    config: AiResearchV4ServerConfig,
    consumerCount: number
): RdKafkaConsumerOverrides {
    assertImageFetchBatchTarget(consumerCount)
    const maximumRecordBytes = config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_IMAGE_BYTES * 2 + 64 * 1024
    return {
        'fetch.message.max.bytes': maximumRecordBytes,
        'max.partition.fetch.bytes': maximumRecordBytes,
        'queued.max.messages.kbytes': Math.max(
            IMAGE_FETCH_MIN_CONSUMER_QUEUE_KBYTES,
            Math.ceil(maximumRecordBytes / 1024),
            Math.floor(IMAGE_FETCH_KAFKA_QUEUE_BUDGET_KBYTES / consumerCount)
        ),
    }
}

export interface ImageFetchBatchHandlers {
    handlers: EachBatch[]
    /** Resolves once every batch started so far has settled, including pooled batches that the Kafka drain gave up on. */
    waitForProcessing(): Promise<void>
}

export function buildImageFetchBatchHandlers(
    consumerCount: number,
    fetchConsumer: Pick<UrlFetchConsumer, 'handleBatch'>,
    fetchRunner: { candidatePool?: Pick<FetchCandidatePool<unknown>, 'createOwner'> },
    batchJoiner: Pick<ImageFetchBatchJoiner, 'handleBatch' | 'waitForProcessing'>
): ImageFetchBatchHandlers {
    const pool = fetchRunner.candidatePool
    const pooledBatches = new Set<Promise<void>>()
    const trackPooledBatch = (batch: Promise<void>): Promise<void> => {
        pooledBatches.add(batch)
        const forget = (): void => {
            pooledBatches.delete(batch)
        }
        batch.then(forget, forget)
        return batch
    }
    const handlers = Array.from({ length: consumerCount }, (): EachBatch => {
        if (!pool) {
            return (messages) => batchJoiner.handleBatch(messages)
        }
        return createPoolWindowBatchHandler(pool.createOwner(), (messages, admission) =>
            trackPooledBatch(fetchConsumer.handleBatch(messages, Date.now(), admission))
        )
    })
    return {
        handlers,
        waitForProcessing: async () => {
            await batchJoiner.waitForProcessing()
            await Promise.allSettled(pooledBatches)
        },
    }
}

export async function shutdownImageFetchConsumers(
    consumers: Pick<KafkaConsumerV2, 'stopConsuming' | 'disconnect'>[],
    startedBatches: Pick<ImageFetchBatchHandlers, 'waitForProcessing'>,
    fetchRunner?: Pick<FetchRunner, 'close'>
): Promise<void> {
    await Promise.allSettled(consumers.map((consumer) => consumer.stopConsuming()))
    await startedBatches.waitForProcessing()
    await Promise.allSettled(consumers.map((consumer) => consumer.disconnect()))
    await fetchRunner?.close()
}

/**
 * The v4 image fetch lane: the fetch policy of the v3 lane over the v4 recorder's URLs, storing each image sealed and
 * unscrubbed in `images-v4`. It reads the team month keys and never writes them, and it uses a share of the configured
 * per-host limits.
 */
export class AiResearchV4ImageFetchServer extends AiResearchV4ConsumerServer {
    private crawlHistoryClient?: DynamoDBClient
    private producerRegistry?: KafkaProducerRegistry<AiResearchV4ImageFetchProducerName>
    private topHog?: TopHog

    protected async startServices(): Promise<void> {
        // Here rather than on the first record. The parser calls into this addon for every URL, and
        // it must answer with a reason rather than raise, so a build that shipped without the addon
        // has to stop the pod at startup instead.
        assertUrlPolicyLoaded()

        const consumerConfigs = buildImageFetchConsumerConfigs(this.config)
        const dryRun = this.config.AI_RESEARCH_V4_IMAGE_FETCH_DRY_RUN
        const { AI_RESEARCH_V4_KEY_TABLE, AI_RESEARCH_V4_KMS_KEY_ARN, AI_RESEARCH_V4_IMAGES_BUCKET } = this.config
        if (!AI_RESEARCH_V4_KEY_TABLE || !AI_RESEARCH_V4_KMS_KEY_ARN || !AI_RESEARCH_V4_IMAGES_BUCKET) {
            throw new Error(
                'the v4 image fetch lane needs AI_RESEARCH_V4_KEY_TABLE, AI_RESEARCH_V4_KMS_KEY_ARN and AI_RESEARCH_V4_IMAGES_BUCKET'
            )
        }
        const historyTable = this.config.AI_RESEARCH_V4_IMAGE_FETCH_HISTORY_TABLE
        if (!historyTable) {
            throw new Error('AI_RESEARCH_V4_IMAGE_FETCH_HISTORY_TABLE must be set for the v4 image fetch lane')
        }
        const dynamoDBTimeoutMs = this.config.AI_RESEARCH_V4_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS
        if (!Number.isFinite(dynamoDBTimeoutMs) || dynamoDBTimeoutMs <= 0) {
            throw new Error(
                `AI_RESEARCH_V4_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS must be a positive number, got ${dynamoDBTimeoutMs}`
            )
        }
        const s3 = buildSessionRecordingS3Client(this.config)
        if (!s3) {
            throw new Error('SESSION_RECORDING_V2_S3_* must be configured for the v4 image fetch lane')
        }
        const region = this.config.SESSION_RECORDING_V2_S3_REGION || 'us-east-1'
        this.crawlHistoryClient = new DynamoDBClient({
            region,
            endpoint: this.config.SESSION_RECORDING_DYNAMODB_ENDPOINT,
            maxAttempts: 5,
            requestHandler: new NodeHttpHandler(),
        })
        const crawlHistory = new DynamoDBCrawlHistory(
            this.crawlHistoryClient,
            historyTable,
            dynamoDBTimeoutMs,
            STORE_BATCH_BUDGET_MS
        )
        await crawlHistory.validateAccess(Date.now())

        const keys = new TeamMonthKeys(
            new DynamoDBClient({ region, endpoint: this.config.SESSION_RECORDING_DYNAMODB_ENDPOINT, maxAttempts: 5 }),
            new KMSClient({ region, maxAttempts: 3 }),
            AI_RESEARCH_V4_KEY_TABLE,
            AI_RESEARCH_V4_KMS_KEY_ARN,
            this.config.AI_RESEARCH_V4_KMS_REQUESTS_PER_SECOND
        )
        const admission = new V4JobAdmission(keys, this.config.AI_RESEARCH_V4_IMAGE_FETCH_KEY_BUDGET_MS)
        const imageSink = new RawImageStore(
            keys,
            s3,
            AI_RESEARCH_V4_IMAGES_BUCKET,
            this.config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_PENDING_PUBLISHES
        )

        // Built even in dry run, so the wiring is exercised by every start rather than only by the
        // one that clears the flag.
        this.producerRegistry = await createV4ImageFetchProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(
            this.config
        )
        const outputs = createV4ImageFetchOutputs().build(this.producerRegistry, this.config)
        this.topHog = new TopHog({
            outputs,
            pipeline: this.config.INGESTION_PIPELINE ?? 'unknown',
            lane: this.config.INGESTION_LANE ?? 'unknown',
        })
        this.topHog.start()
        const topHogMetrics = new ImageFetchTopHogMetrics(this.topHog)
        const producer = this.producerRegistry.getProducer(AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER)
        const publisher = buildFrontierPublisher(producer, this.config.AI_RESEARCH_V4_IMAGE_FETCH_MAX_PENDING_PUBLISHES)
        const deadLetterTopic = this.config.AI_RESEARCH_V4_IMAGE_FETCH_DLQ_TOPIC
        const deadLetters = deadLetterTopic
            ? new KafkaFrontierDeadLetterSink(producer, deadLetterTopic, BLOCKED_IMAGE_FETCH_DEAD_LETTER_TOPICS)
            : null

        const fetchRunner = buildFetchRunner(this.config, publisher, topHogMetrics, imageSink, keys)
        const fetchConsumer = new UrlFetchConsumer(
            crawlHistory,
            publisher,
            {
                seenTtlSeconds: this.config.AI_RESEARCH_V4_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS,
                dryRun,
                admitCandidates: (candidates, nowMs) => admission.admit(candidates, nowMs),
                refreshingSink: imageSink,
            },
            fetchRunner,
            deadLetters,
            topHogMetrics
        )
        logger.info('🌐', 'ai_research_v4_image_fetch_started', {
            dryRun,
            continuousPool: this.config.AI_RESEARCH_V4_IMAGE_FETCH_CONTINUOUS_POOL,
        })

        const batchJoiner = new ImageFetchBatchJoiner(
            imageFetchBatchesPerPass(this.config, consumerConfigs.length),
            (messages) => fetchConsumer.handleBatch(messages, Date.now())
        )
        const batchHandlers = buildImageFetchBatchHandlers(
            consumerConfigs.length,
            fetchConsumer,
            fetchRunner,
            batchJoiner
        )
        const consumerOverrides = buildImageFetchConsumerOverrides(this.config, consumerConfigs.length)
        const consumers = consumerConfigs.map(
            (consumerConfig) => new KafkaConsumerV2(consumerConfig, consumerOverrides)
        )

        this.lifecycle.services.push({
            id: 'ai-research-v4-image-fetch',
            onShutdown: () => shutdownImageFetchConsumers(consumers, batchHandlers, fetchRunner),
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
        const watermark = new CaptureWatermark('ai_research_v4_image_fetch')
        await Promise.all(
            consumers.map((consumer, index) =>
                consumer.connect(
                    (messages) => {
                        watermark.hold(capturedRecords(messages, () => 'image_urls'))
                        return batchHandlers.handlers[index](messages)
                    },
                    (partitions) => {
                        watermark.forget(partitions)
                        return Promise.resolve()
                    },
                    (offsets) => watermark.release(offsets)
                )
            )
        )
    }

    protected getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [],
            additionalCleanup: async () => {
                this.crawlHistoryClient?.destroy()
                try {
                    await this.topHog?.stop()
                } finally {
                    await this.producerRegistry?.disconnectAll()
                }
            },
        }
    }
}

/** Relays the v4 lane's delay tiers back to its frontier. */
export class AiResearchV4ImageFetchRetryServer extends AiResearchV4ConsumerServer {
    private producerRegistry?: KafkaProducerRegistry<AiResearchV4ImageFetchProducerName>

    protected async startServices(): Promise<void> {
        assertOwnImageFetchGroup(this.config.AI_RESEARCH_V4_IMAGE_FETCH_GROUP_ID)
        const topic = this.config.AI_RESEARCH_V4_IMAGE_FETCH_RETRY_TOPIC
        const delayMs = this.config.AI_RESEARCH_V4_IMAGE_FETCH_RETRY_DELAY_MS
        const batchSize = this.config.AI_RESEARCH_V4_IMAGE_FETCH_RETRY_BATCH_SIZE
        const producerDeliveryTimeoutMs = Number(
            this.config.KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_MESSAGE_TIMEOUT_MS
        )
        // A typo here reads as an empty topic name, and librdkafka would subscribe to it and sit
        // idle while the tier filled. Naming the three the publisher writes to also stops a pod
        // draining the frontier itself, which has no period and would publish every record straight
        // back to it.
        if (!V4_IMAGE_FETCH_DELAY_TOPICS.includes(topic)) {
            throw new Error(
                `AI_RESEARCH_V4_IMAGE_FETCH_RETRY_TOPIC must name one of ${V4_IMAGE_FETCH_DELAY_TOPICS.join(', ')}, got "${topic}"`
            )
        }
        if (!Number.isInteger(batchSize) || batchSize < 1) {
            throw new Error(`AI_RESEARCH_V4_IMAGE_FETCH_RETRY_BATCH_SIZE must be positive, got ${batchSize}`)
        }
        if (!Number.isFinite(producerDeliveryTimeoutMs) || producerDeliveryTimeoutMs <= 0) {
            throw new Error(`the image fetch retry producer needs a positive delivery timeout`)
        }

        this.producerRegistry = await createV4ImageFetchProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(
            this.config
        )
        const producer = this.producerRegistry.getProducer(AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER)

        const consumerConfig: KafkaConsumerConfig = {
            topic,
            groupId: `${this.config.AI_RESEARCH_V4_IMAGE_FETCH_GROUP_ID}-retry-${delayMs}`,
            autoCommit: true,
            // Stored after every publish in the batch is acknowledged.
            autoOffsetStore: false,
            fetchBatchSize: batchSize,
        }
        // Set here rather than left to the deployment. This consumer sleeps for the period of its
        // topic inside one batch, and the shared default of 300s would evict the 10m and 1h tiers
        // mid-sleep, then replay the partition into a consumer that sleeps just as long.
        //
        // The batch waits once for its latest broker append timestamp.
        const pollIntervalMs = delayMs + batchSize * producerDeliveryTimeoutMs + POLL_INTERVAL_MARGIN_MS
        if (pollIntervalMs > MAX_POLL_INTERVAL_MS) {
            throw new Error(
                `a delay of ${delayMs}ms and batch of ${batchSize} need a poll interval of ${pollIntervalMs}ms, which is past what Kafka allows`
            )
        }
        const consumer = new KafkaConsumer(consumerConfig, { 'max.poll.interval.ms': pollIntervalMs })
        // The shutdown handler sets this before it disconnects the consumer, so a stopping pod
        // abandons the wait it holds rather than making the rolling deploy wait out a tier period.
        let stopping = false
        const watermark = new CaptureWatermark(`ai_research_v4_image_fetch_retry_${delayMs}`)
        const delayConsumer = new RetryDelayConsumer(producer, {
            isStopping: () => stopping,
            storeOffsets: (messages) => {
                try {
                    const offsets = findOffsetsToCommit(messages)
                    consumer.offsetsStore(offsets)
                    watermark.release(offsets)
                } catch (error) {
                    const code = (error as LibrdKafkaError | undefined)?.code
                    if (!stopping && !REVOKED_PARTITION_CODES.has(code ?? 0)) {
                        throw error
                    }
                    logger.warn('🌐', 'ai_research_v4_image_fetch_retry_offset_store_failed', {
                        partitions: messages.map((message) => message.partition),
                        code,
                        error: error instanceof Error ? error.name : 'unknown',
                    })
                }
            },
            frontierTopic: V4_IMAGE_FETCH_LANE.frontier,
            delayMs,
            heartbeat: () => consumer.reportDeliberateWait(),
        })
        logger.info('🌐', 'ai_research_v4_image_fetch_retry_started', { topic, delayMs, pollIntervalMs })

        await consumer.connect(
            (messages) => {
                watermark.hold(capturedRecords(messages, () => 'image_urls'))
                return delayConsumer.handleBatch(messages)
            },
            (partitions) => {
                watermark.forget(partitions)
                return Promise.resolve()
            }
        )

        this.lifecycle.services.push({
            id: 'ai-research-v4-image-fetch-retry',
            onShutdown: () => {
                stopping = true
                return consumer.disconnect()
            },
            healthcheck: () => consumer.isHealthy(),
        })
    }

    protected getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [],
            additionalCleanup: () => this.producerRegistry?.disconnectAll(),
        }
    }
}
