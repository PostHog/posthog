/** Settings of the v4 AI research lanes. */
import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { KAFKA_CLICKHOUSE_TOPHOG } from '~/common/config/kafka-topics'
import {
    INGESTION_DOWNSTREAM_PRODUCER,
    getDefaultKafkaDownstreamProducerEnvConfig,
} from '~/ingestion/common/outputs/producers'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import {
    getDefaultSessionRecordingApiConfig,
    getDefaultSessionRecordingConfig,
    getDefaultSessionReplayOutputsConfig,
} from '~/ingestion/pipelines/sessionreplay/config'
import { getDefaultKafkaSessionreplayProducerEnvConfig } from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'
import type { IngestionSessionReplayServerConfig } from '~/servers/ingestion-session-replay-server'

import type { AiResearchV4ImageFetchProducerName } from './image-fetch-v4/producer'

export type AiResearchV4Config = {
    /** The v4 image fetch lane: the team month key table, its KMS key, and the bucket fetched images go to. */
    AI_RESEARCH_V4_KEY_TABLE: string
    AI_RESEARCH_V4_KMS_KEY_ARN: string
    AI_RESEARCH_V4_IMAGES_BUCKET: string
    /** KMS decrypt requests per second one pod may send for team month keys. */
    AI_RESEARCH_V4_KMS_REQUESTS_PER_SECOND: number
    /** The v4 lane's consumer group. Its own setting, so a v4 pod never joins a v3 group. Retry tiers add a suffix. */
    AI_RESEARCH_V4_IMAGE_FETCH_GROUP_ID: string
    /** How long all key lookups of one batch may take. A job whose key is not read by then goes to a delay tier. */
    AI_RESEARCH_V4_IMAGE_FETCH_KEY_BUDGET_MS: number
    /**
     * The share of the per registrable domain limits below that the v4 lane uses. The v3 lane's pods hold their own
     * budget, so a host sees both lanes.
     */
    AI_RESEARCH_V4_IMAGE_FETCH_HOST_BUDGET_SHARE: number

    /** US-only, PEM, multiple keys allowed (comma-separated). */
    AI_RESEARCH_V4_IMAGE_FETCH_WEB_BOT_AUTH_PRIVATE_KEYS: string
    /** While true, the fetch lane parses input but sends no request and writes no crawl history. */
    AI_RESEARCH_V4_IMAGE_FETCH_DRY_RUN: boolean
    /** Optional topic for rejected frontier records. Empty commits and drops rejected input without quarantine. */
    AI_RESEARCH_V4_IMAGE_FETCH_DLQ_TOPIC: string
    AI_RESEARCH_V4_IMAGE_FETCH_BATCH_SIZE: number
    /** Kafka group members per image-fetch worker. */
    AI_RESEARCH_V4_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: number
    /** While true, the batches of all group members in one worker join into one fetch pass. While false, each batch starts its own pass. */
    AI_RESEARCH_V4_IMAGE_FETCH_JOIN_MEMBER_BATCHES: boolean
    /**
     * While true, every batch adds its URLs to one pod-wide candidate pool and finishes on its own,
     * and AI_RESEARCH_V4_IMAGE_FETCH_JOIN_MEMBER_BATCHES has no effect.
     */
    AI_RESEARCH_V4_IMAGE_FETCH_CONTINUOUS_POOL: boolean
    /** A group member reads its next batch once fewer of its queued URLs than this can run. */
    AI_RESEARCH_V4_IMAGE_FETCH_POOL_REFILL_RUNNABLE_URLS: number
    /** A group member also waits while this many of its URLs are queued. The wait stops after 30 s to keep the consumer loop healthy, so a member can pass this by about one batch until pass deadlines remove its queued URLs. */
    AI_RESEARCH_V4_IMAGE_FETCH_POOL_MAX_QUEUED_URLS_PER_MEMBER: number
    /** The lane's own crawl history table: the URL history of v4 references, and robots.txt and tdmrep by origin. */
    AI_RESEARCH_V4_IMAGE_FETCH_HISTORY_TABLE: string
    /** Bounds one DynamoDB request so an unavailable store cannot hold the poll loop. */
    AI_RESEARCH_V4_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS: number
    /** The shortest time before the lane fetches a URL again. */
    AI_RESEARCH_V4_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS: number

    /** Optional steady request rate for one registrable domain. Zero uses the concurrency limit only. */
    AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_REQUESTS_PER_SECOND: number
    /** Tokens one idle registrable domain can retain when the steady request rate is enabled. */
    AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BURST: number
    /** Also the worker count for one registrable domain or origin. */
    AI_RESEARCH_V4_IMAGE_FETCH_MAX_CONCURRENT_PER_REGISTRABLE_DOMAIN: number
    /**
     * Requests this pod holds open across every registrable domain at once.
     *
     * The topic key sends one registrable domain to one partition and one pod. Its rate limit lives
     * on that pod. The state limits prevent unbounded in-memory maps.
     *
     * This bounds the pod instead. A body reads into a buffer, so the resident peak is roughly this
     * times AI_RESEARCH_V4_IMAGE_FETCH_MAX_IMAGE_BYTES, and the sockets and the DNS lookups
     * scale with it too. Raise the pod's memory before you raise this.
     */
    AI_RESEARCH_V4_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS: number
    /** Image writes to S3, and republished frontier records, in flight at once. */
    AI_RESEARCH_V4_IMAGE_FETCH_MAX_PENDING_PUBLISHES: number
    /**
     * Wall time the fetch pass of one poll batch may take.
     *
     * A batch can hold more URLs for one registrable domain than a polite rate carries in this
     * time. What the pass does not reach goes to a delay topic without spending a hop. The value
     * sits well inside Kafka's max.poll.interval.ms of 300s, which the crawl history round trips
     * share.
     */
    AI_RESEARCH_V4_IMAGE_FETCH_REQUEST_BUDGET_MS: number
    /** Refused before the body when the response declares more, and abandoned mid-body when it declares nothing. */
    AI_RESEARCH_V4_IMAGE_FETCH_MAX_IMAGE_BYTES: number
    /** Covers one URL including its redirects, separate from the connect timeout of the shared request layer. */
    AI_RESEARCH_V4_IMAGE_FETCH_REQUEST_TIMEOUT_MS: number
    AI_RESEARCH_V4_IMAGE_FETCH_MAX_REDIRECTS: number
    /** Consecutive failures before this pod stops sending to one registrable domain. */
    AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_FAILURES: number
    AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_COOLDOWN_MS: number
    /** The longest calculated breaker back-off. A longer valid `Retry-After` remains authoritative. */
    AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_MAX_COOLDOWN_MS: number
    /** Registrable domains one pod holds request-control state for. */
    AI_RESEARCH_V4_IMAGE_FETCH_MAX_TRACKED_REGISTRABLE_DOMAINS: number
    /** Origins one pod holds configuration and crawl-delay state for. */
    AI_RESEARCH_V4_IMAGE_FETCH_MAX_TRACKED_ORIGINS: number

    /**
     * The delay topic one retry pod drains, and the period every record in it waits.
     *
     * One server runs every tier, so three deployments of one image cover 1 minute, 10 minutes, and
     * one hour. The pod's `max.poll.interval.ms` must exceed the period, or the broker evicts the
     * consumer while it sleeps.
     */
    AI_RESEARCH_V4_IMAGE_FETCH_RETRY_TOPIC: string
    AI_RESEARCH_V4_IMAGE_FETCH_RETRY_DELAY_MS: number
    /** Records released together after one wait based on the latest broker append timestamp. */
    AI_RESEARCH_V4_IMAGE_FETCH_RETRY_BATCH_SIZE: number

    /** Where the lane's TopHog rows go. */
    AI_RESEARCH_V4_IMAGE_FETCH_TOPHOG_TOPIC: string
    AI_RESEARCH_V4_IMAGE_FETCH_TOPHOG_PRODUCER: AiResearchV4ImageFetchProducerName

    /**
     * The lane's own producer on the replay cluster, for frontier and delay tier records. Its broker and security
     * settings are those of the replay producer.
     */
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_COMPRESSION_CODEC: string
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_LINGER_MS: string
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: string
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: string
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_MESSAGE_MAX_BYTES: string
    /** A short local delivery timeout, so a slow topic fails a batch fast instead of holding its offsets. */
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_MESSAGE_TIMEOUT_MS: string

    /** The v4 index sink: the bucket its Parquet files go to, under `index/`. */
    AI_RESEARCH_V4_RRWEB_BUCKET: string
    /** The v4 index sink's consumer group. Its own setting, so a v4 sink pod never joins the v3 sink group. */
    AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID: string
    /**
     * The v4 sink writes its files this long after its last flush, or when the buffer reaches either size below,
     * whichever comes first. The byte size counts Kafka message bytes, so it also bounds the buffer's memory.
     */
    AI_RESEARCH_V4_PARQUET_FLUSH_INTERVAL_MS: number
    AI_RESEARCH_V4_PARQUET_MAX_ROWS: number
    AI_RESEARCH_V4_PARQUET_MAX_BYTES: number
    /** Rows per row group in a v4 index file, so a large file has few row groups. */
    AI_RESEARCH_V4_PARQUET_ROW_GROUP_ROWS: number
}

export function getDefaultAiResearchV4Config(): AiResearchV4Config {
    return {
        AI_RESEARCH_V4_KEY_TABLE: '',
        AI_RESEARCH_V4_KMS_KEY_ARN: '',
        AI_RESEARCH_V4_IMAGES_BUCKET: '',
        AI_RESEARCH_V4_KMS_REQUESTS_PER_SECOND: 150,
        AI_RESEARCH_V4_IMAGE_FETCH_GROUP_ID: 'ai-research-v4-image-fetch',
        AI_RESEARCH_V4_IMAGE_FETCH_KEY_BUDGET_MS: 60_000,
        AI_RESEARCH_V4_IMAGE_FETCH_HOST_BUDGET_SHARE: 0.25,

        AI_RESEARCH_V4_IMAGE_FETCH_WEB_BOT_AUTH_PRIVATE_KEYS: '',
        AI_RESEARCH_V4_IMAGE_FETCH_DRY_RUN: true,
        AI_RESEARCH_V4_IMAGE_FETCH_DLQ_TOPIC: '',
        AI_RESEARCH_V4_IMAGE_FETCH_BATCH_SIZE: 500,
        AI_RESEARCH_V4_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 2,
        AI_RESEARCH_V4_IMAGE_FETCH_JOIN_MEMBER_BATCHES: true,
        AI_RESEARCH_V4_IMAGE_FETCH_CONTINUOUS_POOL: false,
        AI_RESEARCH_V4_IMAGE_FETCH_POOL_REFILL_RUNNABLE_URLS: 100,
        AI_RESEARCH_V4_IMAGE_FETCH_POOL_MAX_QUEUED_URLS_PER_MEMBER: 2_000,
        AI_RESEARCH_V4_IMAGE_FETCH_HISTORY_TABLE: '',
        AI_RESEARCH_V4_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS: 5_000,
        AI_RESEARCH_V4_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS: 30 * 24 * 60 * 60,
        AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_REQUESTS_PER_SECOND: 0,
        AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BURST: 6,
        AI_RESEARCH_V4_IMAGE_FETCH_MAX_CONCURRENT_PER_REGISTRABLE_DOMAIN: 6,
        AI_RESEARCH_V4_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS: 300,
        AI_RESEARCH_V4_IMAGE_FETCH_MAX_PENDING_PUBLISHES: 100,
        AI_RESEARCH_V4_IMAGE_FETCH_REQUEST_BUDGET_MS: 40_000,
        AI_RESEARCH_V4_IMAGE_FETCH_MAX_IMAGE_BYTES: 20 * 1024 * 1024,
        AI_RESEARCH_V4_IMAGE_FETCH_REQUEST_TIMEOUT_MS: 10_000,
        AI_RESEARCH_V4_IMAGE_FETCH_MAX_REDIRECTS: 3,
        AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_FAILURES: 5,
        AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_COOLDOWN_MS: 60_000,
        AI_RESEARCH_V4_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_MAX_COOLDOWN_MS: 60 * 60 * 1000,
        AI_RESEARCH_V4_IMAGE_FETCH_MAX_TRACKED_REGISTRABLE_DOMAINS: 20_000,
        AI_RESEARCH_V4_IMAGE_FETCH_MAX_TRACKED_ORIGINS: 20_000,
        AI_RESEARCH_V4_IMAGE_FETCH_RETRY_TOPIC: '',
        AI_RESEARCH_V4_IMAGE_FETCH_RETRY_DELAY_MS: 60_000,
        AI_RESEARCH_V4_IMAGE_FETCH_RETRY_BATCH_SIZE: 500,

        AI_RESEARCH_V4_IMAGE_FETCH_TOPHOG_TOPIC: KAFKA_CLICKHOUSE_TOPHOG,
        AI_RESEARCH_V4_IMAGE_FETCH_TOPHOG_PRODUCER: INGESTION_DOWNSTREAM_PRODUCER,

        KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_COMPRESSION_CODEC: 'snappy',
        KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_LINGER_MS: '',
        KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: '50000',
        KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: '32768',
        KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_MESSAGE_MAX_BYTES: `${40 * 1024 * 1024 + 64 * 1024}`,
        KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_MESSAGE_TIMEOUT_MS: '20000',

        AI_RESEARCH_V4_RRWEB_BUCKET: '',
        AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID: 'ai-research-v4-parquet-sink',
        AI_RESEARCH_V4_PARQUET_FLUSH_INTERVAL_MS: 10 * 60 * 1000,
        AI_RESEARCH_V4_PARQUET_MAX_ROWS: 1_000_000,
        AI_RESEARCH_V4_PARQUET_MAX_BYTES: 128 * 1024 * 1024,
        AI_RESEARCH_V4_PARQUET_ROW_GROUP_ROWS: 131_072,
    }
}

export function getAiResearchV4Config(env: Record<string, string | undefined> = process.env): AiResearchV4Config {
    return overrideConfigWithEnv(getDefaultAiResearchV4Config(), env)
}

/** Full config of a v4 server: the replay settings it shares with the primary ingester, plus the v4 settings. */
export type AiResearchV4ServerConfig = IngestionSessionReplayServerConfig & AiResearchV4Config

export function buildAiResearchV4ServerConfig(
    config: Partial<AiResearchV4ServerConfig> = {}
): AiResearchV4ServerConfig {
    return {
        ...defaultConfig,
        ...overrideConfigWithEnv(getDefaultIngestionConsumerConfig()),
        ...overrideConfigWithEnv(getDefaultKafkaDownstreamProducerEnvConfig()),
        ...overrideConfigWithEnv(getDefaultKafkaSessionreplayProducerEnvConfig()),
        ...overrideConfigWithEnv(getDefaultSessionRecordingConfig()),
        ...overrideConfigWithEnv(getDefaultSessionRecordingApiConfig()),
        ...overrideConfigWithEnv(getDefaultSessionReplayOutputsConfig()),
        ...getAiResearchV4Config(),
        ...config,
    }
}
