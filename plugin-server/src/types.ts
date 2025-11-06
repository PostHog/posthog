import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'
import { Kafka } from 'kafkajs'
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { VM } from 'vm2'

import {
    Element,
    PluginAttachment,
    PluginConfigSchema,
    PluginEvent,
    PluginSettings,
    PostHogEvent,
    ProcessedPluginEvent,
    Properties,
    Webhook,
} from '@posthog/plugin-scaffold'

import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { IntegrationManagerService } from './cdp/services/managers/integration-manager.service'
import { CyclotronJobQueueKind, CyclotronJobQueueSource } from './cdp/types'
import { EncryptedFields } from './cdp/utils/encryption-utils'
import { InternalCaptureService } from './common/services/internal-capture'
import type { CookielessManager } from './ingestion/cookieless/cookieless-manager'
import { KafkaProducerWrapper } from './kafka/producer'
import { ActionManagerCDP } from './utils/action-manager-cdp'
import { Celery } from './utils/db/celery'
import { DB } from './utils/db/db'
import { PostgresRouter } from './utils/db/postgres'
import { GeoIPService } from './utils/geoip'
import { ObjectStorage } from './utils/object_storage'
import { PubSub } from './utils/pubsub'
import { TeamManager } from './utils/team-manager'
import { TeamSecretKeysManager } from './utils/team-secret-keys-manager'
import { UUID } from './utils/utils'
import { ActionManager } from './worker/ingestion/action-manager'
import { ActionMatcher } from './worker/ingestion/action-matcher'
import { AppMetrics } from './worker/ingestion/app-metrics'
import { GroupTypeManager } from './worker/ingestion/group-type-manager'
import { ClickhouseGroupRepository } from './worker/ingestion/groups/repositories/clickhouse-group-repository'
import { GroupRepository } from './worker/ingestion/groups/repositories/group-repository.interface'
import { PersonRepository } from './worker/ingestion/persons/repositories/person-repository'
import { RustyHook } from './worker/rusty-hook'
import { PluginsApiKeyManager } from './worker/vm/extensions/helpers/api-key-manager'
import { RootAccessManager } from './worker/vm/extensions/helpers/root-acess-manager'
import { PluginInstance } from './worker/vm/lazy'

export { Element } from '@posthog/plugin-scaffold' // Re-export Element from scaffolding, for backwards compat.

type Brand<K, T> = K & { __brand: T }

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export enum KafkaSecurityProtocol {
    Plaintext = 'PLAINTEXT',
    SaslPlaintext = 'SASL_PLAINTEXT',
    Ssl = 'SSL',
    SaslSsl = 'SASL_SSL',
}

export enum KafkaSaslMechanism {
    Plain = 'plain',
    ScramSha256 = 'scram-sha-256',
    ScramSha512 = 'scram-sha-512',
}

export enum PluginServerMode {
    ingestion_v2 = 'ingestion-v2',
    local_cdp = 'local-cdp',
    async_webhooks = 'async-webhooks',
    recordings_blob_ingestion_v2 = 'recordings-blob-ingestion-v2',
    recordings_blob_ingestion_v2_overflow = 'recordings-blob-ingestion-v2-overflow',
    cdp_processed_events = 'cdp-processed-events',
    cdp_person_updates = 'cdp-person-updates',
    cdp_internal_events = 'cdp-internal-events',
    cdp_cyclotron_worker = 'cdp-cyclotron-worker',
    cdp_behavioural_events = 'cdp-behavioural-events',
    cdp_cohort_membership = 'cdp-cohort-membership',
    cdp_cyclotron_worker_hogflow = 'cdp-cyclotron-worker-hogflow',
    cdp_cyclotron_worker_delay = 'cdp-cyclotron-worker-delay',
    cdp_api = 'cdp-api',
    cdp_legacy_on_event = 'cdp-legacy-on-event',
    evaluation_scheduler = 'evaluation-scheduler',
    ingestion_logs = 'ingestion-logs',
}

export const stringToPluginServerMode = Object.fromEntries(
    Object.entries(PluginServerMode).map(([key, value]) => [
        value,
        PluginServerMode[key as keyof typeof PluginServerMode],
    ])
) as Record<string, PluginServerMode>

interface HealthCheckResultResponse {
    service: string
    status: 'ok' | 'error' | 'degraded'
    message?: string
    details?: Record<string, any>
}

export abstract class HealthCheckResult {
    public status: 'ok' | 'error' | 'degraded'

    constructor(status: 'ok' | 'error' | 'degraded') {
        this.status = status
    }

    public abstract toResponse(serviceId: string): HealthCheckResultResponse

    public isError(): boolean {
        return this.status === 'error'
    }
}

export class HealthCheckResultOk extends HealthCheckResult {
    constructor() {
        super('ok')
    }
    public toResponse(serviceId: string): HealthCheckResultResponse {
        return { service: serviceId, status: this.status }
    }
}

export class HealthCheckResultError extends HealthCheckResult {
    constructor(
        public message: string,
        public details: Record<string, any>
    ) {
        super('error')
    }

    public toResponse(serviceId: string): HealthCheckResultResponse {
        return { service: serviceId, status: this.status, message: this.message, details: this.details }
    }
}

export class HealthCheckResultDegraded extends HealthCheckResult {
    constructor(
        public message: string,
        public details: Record<string, any>
    ) {
        super('degraded')
    }
    public toResponse(serviceId: string): HealthCheckResultResponse {
        return { service: serviceId, status: this.status, message: this.message, details: this.details }
    }
}

export type PluginServerService = {
    id: string
    onShutdown: () => Promise<any>
    healthcheck: () => HealthCheckResult | Promise<HealthCheckResult>
}

export type CdpConfig = {
    CDP_WATCHER_COST_ERROR: number // The max cost of an erroring function
    CDP_WATCHER_HOG_COST_TIMING: number // The max cost of a slow function
    CDP_WATCHER_HOG_COST_TIMING_LOWER_MS: number // The lower bound in ms where the timing cost is not incurred
    CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: number // The upper bound in ms where the timing cost is fully incurred
    CDP_WATCHER_ASYNC_COST_TIMING: number // The max cost of a slow async function
    CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS: number // The lower bound in ms where the async timing cost is not incurred
    CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS: number // The upper bound in ms where the async timing cost is fully incurred
    CDP_WATCHER_THRESHOLD_DEGRADED: number // Percentage of the bucket where we count it as degraded
    CDP_WATCHER_BUCKET_SIZE: number // The total bucket size
    CDP_WATCHER_TTL: number // The expiry for the rate limit key
    CDP_WATCHER_STATE_LOCK_TTL: number // The expiry for the state lock key preventing transitions too fast
    CDP_WATCHER_REFILL_RATE: number // The number of tokens to be refilled per second
    CDP_WATCHER_DISABLED_TEMPORARY_TTL: number // How long a function should be temporarily disabled for
    CDP_WATCHER_DISABLED_TEMPORARY_MAX_COUNT: number // How many times a function can be disabled before it is disabled permanently
    CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS: boolean // If true then degraded functions will be automatically disabled
    CDP_WATCHER_SEND_EVENTS: boolean // If true then the watcher will send events to posthog for messaging
    CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS: number // How long to buffer results before observing them
    CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS: number // How many results to buffer before observing them
    CDP_RATE_LIMITER_BUCKET_SIZE: number // The total bucket size
    CDP_RATE_LIMITER_REFILL_RATE: number // The number of tokens to be refilled per second
    CDP_RATE_LIMITER_TTL: number // The expiry for the rate limit key
    CDP_HOG_FILTERS_TELEMETRY_TEAMS: string
    CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_KIND: CyclotronJobQueueKind
    CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: CyclotronJobQueueSource
    CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING: string // A comma-separated list of queue to mode like `hog:kafka,fetch:postgres,*:kafka` with * being the default
    CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_TEAM_MAPPING: string // Like the above but with a team check too
    CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_FORCE_SCHEDULED_TO_POSTGRES: boolean // If true then scheduled jobs will be routed to postgres even if they are mapped to kafka

    CDP_LEGACY_EVENT_CONSUMER_GROUP_ID: string
    CDP_LEGACY_EVENT_CONSUMER_TOPIC: string
    CDP_LEGACY_EVENT_REDIRECT_TOPIC: string // If set then this consumer will emit to this topic instead of processing

    CDP_CYCLOTRON_BATCH_DELAY_MS: number
    CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: number
    CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: boolean
    CDP_CYCLOTRON_COMPRESS_VM_STATE: boolean
    CDP_CYCLOTRON_USE_BULK_COPY_JOB: boolean
    CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: boolean
    CDP_REDIS_HOST: string
    CDP_REDIS_PORT: number
    CDP_REDIS_PASSWORD: string

    // Heap dump configuration
    HEAP_DUMP_ENABLED: boolean
    HEAP_DUMP_S3_BUCKET: string
    HEAP_DUMP_S3_PREFIX: string
    HEAP_DUMP_S3_ENDPOINT: string
    HEAP_DUMP_S3_REGION: string
    CDP_EVENT_PROCESSOR_EXECUTE_FIRST_STEP: boolean
    CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN: string
    CDP_FETCH_RETRIES: number
    CDP_FETCH_BACKOFF_BASE_MS: number
    CDP_FETCH_BACKOFF_MAX_MS: number
    CDP_OVERFLOW_QUEUE_ENABLED: boolean

    // topic that plugin VM capture events are produced to
    CDP_PLUGIN_CAPTURE_EVENTS_TOPIC: string

    HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC: string
    HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC: string

    CDP_EMAIL_TRACKING_URL: string
}

export type IngestionConsumerConfig = {
    // New config variables used by the new IngestionConsumer
    INGESTION_CONSUMER_GROUP_ID: string
    INGESTION_CONSUMER_CONSUME_TOPIC: string
    INGESTION_CONSUMER_DLQ_TOPIC: string
    /** If set then overflow routing is enabled and the topic is used for overflow events */
    INGESTION_CONSUMER_OVERFLOW_TOPIC: string
    /** If set the ingestion consumer doesn't process events the usual way but rather just writes to a dummy topic */
    INGESTION_CONSUMER_TESTING_TOPIC: string
}

export type LogsIngestionConsumerConfig = {
    LOGS_INGESTION_CONSUMER_GROUP_ID: string
    LOGS_INGESTION_CONSUMER_CONSUME_TOPIC: string
    LOGS_INGESTION_CONSUMER_OVERFLOW_TOPIC: string
    LOGS_INGESTION_CONSUMER_DLQ_TOPIC: string
    LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC: string
}

/**
 * The mode of db batch writes to use for person batch writing
 * NO_ASSERT: No assertions are made, we write the latest value in memory to the DB (no locks)
 * ASSERT_VERSION: Assert that the current db version is the same as the version in memory (no locks)
 */
export type PersonBatchWritingDbWriteMode = 'NO_ASSERT' | 'ASSERT_VERSION'
export type PersonBatchWritingMode = 'BATCH' | 'SHADOW' | 'NONE'

export interface PluginsServerConfig extends CdpConfig, IngestionConsumerConfig, LogsIngestionConsumerConfig {
    INSTRUMENT_THREAD_PERFORMANCE: boolean
    OTEL_EXPORTER_OTLP_ENDPOINT: string
    OTEL_SDK_DISABLED: boolean
    OTEL_TRACES_SAMPLER_ARG: number
    OTEL_MAX_SPANS_PER_GROUP: number
    OTEL_MIN_SPAN_DURATION_MS: number
    TASKS_PER_WORKER: number // number of parallel tasks per worker thread
    INGESTION_CONCURRENCY: number // number of parallel event ingestion queues per batch
    INGESTION_BATCH_SIZE: number // kafka consumer batch size
    INGESTION_OVERFLOW_ENABLED: boolean // whether or not overflow rerouting is enabled (only used by analytics-ingestion)
    INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID: string // comma-separated list of either tokens or token:distinct_id combinations to force events to route to overflow
    INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY: boolean // whether or not Kafka message keys should be preserved or discarded when messages are rerouted to overflow
    PERSON_BATCH_WRITING_DB_WRITE_MODE: PersonBatchWritingDbWriteMode // the mode of db batch writes to use for person batch writing
    PERSON_BATCH_WRITING_OPTIMISTIC_UPDATES_ENABLED: boolean // whether to use optimistic updates for persons table
    PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES: number // maximum number of concurrent updates to persons table per batch
    PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES: number // maximum number of retries for optimistic update
    PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS: number // starting interval for exponential backoff between retries for optimistic update
    PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE: number
    PERSON_PROPERTIES_DB_CONSTRAINT_LIMIT_BYTES: number // maximum size in bytes for person properties JSON as stored, checked via pg_column_size(properties)
    PERSON_PROPERTIES_TRIM_TARGET_BYTES: number // target size in bytes we trim JSON to before writing (customer-facing 512kb)
    // Limit per merge for moving distinct IDs. 0 disables limiting.
    PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: number
    // Topic for async person merge processing
    PERSON_MERGE_ASYNC_TOPIC: string
    // Enable async person merge processing
    PERSON_MERGE_ASYNC_ENABLED: boolean
    // Batch size for sync person merge processing (0 = unlimited)
    PERSON_MERGE_SYNC_BATCH_SIZE: number
    GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES: number // maximum number of concurrent updates to groups table per batch
    GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES: number // maximum number of retries for optimistic update
    GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS: number // starting interval for exponential backoff between retries for optimistic update
    PERSONS_DUAL_WRITE_ENABLED: boolean // Enable dual-write mode for persons to both primary and migration databases
    PERSONS_DUAL_WRITE_COMPARISON_ENABLED: boolean // Enable comparison metrics between primary and secondary DBs during dual-write
    GROUPS_DUAL_WRITE_ENABLED: boolean // Enable dual-write mode for groups to both primary and migration databases
    GROUPS_DUAL_WRITE_COMPARISON_ENABLED: boolean // Enable comparison metrics between primary and secondary DBs during dual-write
    TASK_TIMEOUT: number // how many seconds until tasks are timed out
    DATABASE_URL: string // Postgres database URL
    DATABASE_READONLY_URL: string // Optional read-only replica to the main Postgres database
    PERSONS_DATABASE_URL: string // Optional read-write Postgres database for persons
    BEHAVIORAL_COHORTS_DATABASE_URL: string // Optional read-write Postgres database for behavioral cohorts
    PERSONS_READONLY_DATABASE_URL: string // Optional read-only replica to the persons Postgres database
    PERSONS_MIGRATION_DATABASE_URL: string // Read-write Postgres database for persons during dual write/migration
    PERSONS_MIGRATION_READONLY_DATABASE_URL: string // Optional read-only replica to the persons Postgres database during dual write/migration
    PLUGIN_STORAGE_DATABASE_URL: string // Optional read-write Postgres database for plugin storage
    POSTGRES_CONNECTION_POOL_SIZE: number
    POSTHOG_DB_NAME: string | null
    POSTHOG_DB_USER: string
    POSTHOG_DB_PASSWORD: string
    POSTHOG_POSTGRES_HOST: string
    POSTHOG_POSTGRES_PORT: number
    POSTGRES_BEHAVIORAL_COHORTS_HOST: string
    POSTGRES_BEHAVIORAL_COHORTS_USER: string
    POSTGRES_BEHAVIORAL_COHORTS_PASSWORD: string
    CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: string
    CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    // Redis url pretty much only used locally / self hosted
    REDIS_URL: string
    // Redis params for the ingestion services
    INGESTION_REDIS_HOST: string
    INGESTION_REDIS_PORT: number
    // Redis params for the core posthog (django+celery) services
    POSTHOG_REDIS_PASSWORD: string
    POSTHOG_REDIS_HOST: string
    POSTHOG_REDIS_PORT: number
    // Common redis params
    REDIS_POOL_MIN_SIZE: number // minimum number of Redis connections to use per thread
    REDIS_POOL_MAX_SIZE: number // maximum number of Redis connections to use per thread

    CONSUMER_BATCH_SIZE: number // Primarily for kafka consumers the batch size to use
    CONSUMER_MAX_HEARTBEAT_INTERVAL_MS: number // Primarily for kafka consumers the max heartbeat interval to use after which it will be considered unhealthy
    CONSUMER_LOOP_STALL_THRESHOLD_MS: number // Threshold in ms after which the consumer loop is considered stalled
    CONSUMER_LOG_STATS_LEVEL: LogLevel // Log level for consumer statistics
    CONSUMER_LOOP_BASED_HEALTH_CHECK: boolean // Use consumer loop monitoring for health checks instead of heartbeats
    CONSUMER_MAX_BACKGROUND_TASKS: number
    CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE: boolean
    CONSUMER_AUTO_CREATE_TOPICS: boolean

    // Kafka params - identical for client and producer
    KAFKA_HOSTS: string // comma-delimited Kafka hosts
    KAFKA_SECURITY_PROTOCOL: KafkaSecurityProtocol | undefined
    KAFKA_CLIENT_RACK: string | undefined

    // Other methods that are generally only used by self-hosted users
    KAFKA_CLIENT_CERT_B64: string | undefined
    KAFKA_CLIENT_CERT_KEY_B64: string | undefined
    KAFKA_TRUSTED_CERT_B64: string | undefined
    KAFKA_SASL_MECHANISM: KafkaSaslMechanism | undefined
    KAFKA_SASL_USER: string | undefined
    KAFKA_SASL_PASSWORD: string | undefined

    // Consumer specific settings (deprecated but cant be removed until legacy onevent consumer is removed)
    KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS: number | null
    KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS: number
    APP_METRICS_FLUSH_FREQUENCY_MS: number
    APP_METRICS_FLUSH_MAX_QUEUE_SIZE: number
    BASE_DIR: string // base path for resolving local plugins
    PLUGINS_DEFAULT_LOG_LEVEL: PluginLogLevel
    LOG_LEVEL: LogLevel
    HTTP_SERVER_PORT: number
    SCHEDULE_LOCK_TTL: number // how many seconds to hold the lock for the schedule
    MMDB_FILE_LOCATION: string // if set we will load the MMDB file from this location instead of downloading it
    DISTINCT_ID_LRU_SIZE: number
    EVENT_PROPERTY_LRU_SIZE: number // size of the event property tracker's LRU cache (keyed by [team.id, event])
    HEALTHCHECK_MAX_STALE_SECONDS: number // maximum number of seconds the plugin server can go without ingesting events before the healthcheck fails
    SITE_URL: string
    TEMPORAL_HOST: string
    TEMPORAL_PORT: string | undefined
    TEMPORAL_NAMESPACE: string
    TEMPORAL_CLIENT_ROOT_CA: string | undefined
    TEMPORAL_CLIENT_CERT: string | undefined
    TEMPORAL_CLIENT_KEY: string | undefined
    KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY: number // (advanced) how many kafka partitions the plugin server should consume from concurrently
    PERSON_INFO_CACHE_TTL: number
    KAFKA_HEALTHCHECK_SECONDS: number
    OBJECT_STORAGE_ENABLED: boolean // Disables or enables the use of object storage. It will become mandatory to use object storage
    OBJECT_STORAGE_REGION: string // s3 region
    OBJECT_STORAGE_ENDPOINT: string // s3 endpoint
    OBJECT_STORAGE_ACCESS_KEY_ID: string
    OBJECT_STORAGE_SECRET_ACCESS_KEY: string
    OBJECT_STORAGE_BUCKET: string // the object storage bucket name
    PLUGIN_SERVER_MODE: PluginServerMode | null
    PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE: string | null // TODO: shouldn't be a string probably
    PLUGIN_LOAD_SEQUENTIALLY: boolean // could help with reducing memory usage spikes on startup
    KAFKAJS_LOG_LEVEL: 'NOTHING' | 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'
    MAX_TEAM_ID_TO_BUFFER_ANONYMOUS_EVENTS_FOR: number
    EVENT_OVERFLOW_BUCKET_CAPACITY: number
    EVENT_OVERFLOW_BUCKET_REPLENISH_RATE: number
    KAFKA_BATCH_START_LOGGING_ENABLED: boolean
    /** Label of the PostHog Cloud environment. Null if not running PostHog Cloud. @example 'US' */
    CLOUD_DEPLOYMENT: string | null
    EXTERNAL_REQUEST_TIMEOUT_MS: number
    EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS: number
    EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS: number
    EXTERNAL_REQUEST_CONNECTIONS: number
    DROP_EVENTS_BY_TOKEN_DISTINCT_ID: string
    SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID: string
    RELOAD_PLUGIN_JITTER_MAX_MS: number
    RUSTY_HOOK_FOR_TEAMS: string
    RUSTY_HOOK_ROLLOUT_PERCENTAGE: number
    RUSTY_HOOK_URL: string
    HOG_HOOK_URL: string
    SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: boolean
    PIPELINE_STEP_STALLED_LOG_TIMEOUT: number
    CAPTURE_CONFIG_REDIS_HOST: string | null // Redis cluster to use to coordinate with capture (overflow, routing)
    LAZY_LOADER_DEFAULT_BUFFER_MS: number
    LAZY_LOADER_MAX_SIZE: number
    CAPTURE_INTERNAL_URL: string

    // local directory might be a volume mount or a directory on disk (e.g. in local dev)
    SESSION_RECORDING_LOCAL_DIRECTORY: string
    SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS: number
    SESSION_RECORDING_MAX_BUFFER_SIZE_KB: number
    SESSION_RECORDING_BUFFER_AGE_IN_MEMORY_MULTIPLIER: number
    SESSION_RECORDING_BUFFER_AGE_JITTER: number
    SESSION_RECORDING_REMOTE_FOLDER: string
    SESSION_RECORDING_REDIS_PREFIX: string
    SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION: boolean
    SESSION_RECORDING_PARALLEL_CONSUMPTION: boolean
    SESSION_RECORDING_CONSOLE_LOGS_INGESTION_ENABLED: boolean
    SESSION_RECORDING_REPLAY_EVENTS_INGESTION_ENABLED: boolean
    // a single partition which will output many more log messages to the console
    // useful when that partition is lagging unexpectedly
    // allows comma separated list of partition numbers or '*' for all
    SESSION_RECORDING_DEBUG_PARTITION: string | undefined
    // overflow detection, updating Redis for capture to move the traffic away
    SESSION_RECORDING_OVERFLOW_ENABLED: boolean
    SESSION_RECORDING_OVERFLOW_BUCKET_CAPACITY: number
    SESSION_RECORDING_OVERFLOW_BUCKET_REPLENISH_RATE: number
    SESSION_RECORDING_OVERFLOW_MIN_PER_BATCH: number
    SESSION_RECORDING_MAX_PARALLEL_FLUSHES: number

    POSTHOG_SESSION_RECORDING_REDIS_HOST: string | undefined
    POSTHOG_SESSION_RECORDING_REDIS_PORT: number | undefined

    ENCRYPTION_SALT_KEYS: string

    CYCLOTRON_DATABASE_URL: string
    CYCLOTRON_SHARD_DEPTH_LIMIT: number

    // posthog
    POSTHOG_API_KEY: string
    POSTHOG_HOST_URL: string

    // cookieless, should match the values in rust/feature-flags/src/config.rs
    COOKIELESS_DISABLED: boolean
    COOKIELESS_FORCE_STATELESS_MODE: boolean
    COOKIELESS_DELETE_EXPIRED_LOCAL_SALTS_INTERVAL_MS: number
    COOKIELESS_SESSION_TTL_SECONDS: number
    COOKIELESS_SALT_TTL_SECONDS: number
    COOKIELESS_SESSION_INACTIVITY_MS: number
    COOKIELESS_IDENTIFIES_TTL_SECONDS: number
    COOKIELESS_REDIS_HOST: string
    COOKIELESS_REDIS_PORT: number

    // Timestamp comparison logging (0.0 = disabled, 1.0 = 100% sampling)
    TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: number

    SESSION_RECORDING_MAX_BATCH_SIZE_KB: number
    SESSION_RECORDING_MAX_BATCH_AGE_MS: number
    SESSION_RECORDING_V2_S3_BUCKET: string
    SESSION_RECORDING_V2_S3_PREFIX: string
    SESSION_RECORDING_V2_S3_ENDPOINT: string
    SESSION_RECORDING_V2_S3_REGION: string
    SESSION_RECORDING_V2_S3_ACCESS_KEY_ID: string
    SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY: string
    SESSION_RECORDING_V2_S3_TIMEOUT_MS: number
    SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC: string
    SESSION_RECORDING_V2_CONSOLE_LOG_ENTRIES_KAFKA_TOPIC: string
    SESSION_RECORDING_V2_CONSOLE_LOG_STORE_SYNC_BATCH_LIMIT: number
    SESSION_RECORDING_V2_MAX_EVENTS_PER_SESSION_PER_BATCH: number

    // New: switchover flag for v2 session recording metadata
    SESSION_RECORDING_V2_METADATA_SWITCHOVER: string

    // Destination Migration Diffing
    DESTINATION_MIGRATION_DIFFING_ENABLED: boolean

    PROPERTY_DEFS_CONSUMER_GROUP_ID: string
    PROPERTY_DEFS_CONSUMER_CONSUME_TOPIC: string
    PROPERTY_DEFS_CONSUMER_ENABLED_TEAMS: string
    PROPERTY_DEFS_WRITE_DISABLED: boolean

    CDP_HOG_WATCHER_SAMPLE_RATE: number
    // for enablement/sampling of expensive person JSONB sizes; value in [0,1]
    PERSON_JSONB_SIZE_ESTIMATE_ENABLE: number
    USE_DYNAMIC_EVENT_INGESTION_RESTRICTION_CONFIG: boolean

    // Workflows
    MAILJET_PUBLIC_KEY: string
    MAILJET_SECRET_KEY: string

    // SES
    SES_ENDPOINT: string
    SES_ACCESS_KEY_ID: string
    SES_SECRET_ACCESS_KEY: string
    SES_REGION: string

    // Heap dump configuration
    HEAP_DUMP_ENABLED: boolean
    HEAP_DUMP_S3_BUCKET: string
    HEAP_DUMP_S3_PREFIX: string
    HEAP_DUMP_S3_ENDPOINT: string
    HEAP_DUMP_S3_REGION: string

    // Pod termination
    POD_TERMINATION_ENABLED: boolean
    POD_TERMINATION_BASE_TIMEOUT_MINUTES: number
    POD_TERMINATION_JITTER_MINUTES: number
}

export interface Hub extends PluginsServerConfig {
    instanceId: UUID
    // what tasks this server will tackle - e.g. ingestion, scheduled plugins or others.
    capabilities: PluginServerCapabilities
    // active connections to Postgres, Redis, Kafka
    db: DB
    postgres: PostgresRouter
    postgresPersonMigration: PostgresRouter
    redisPool: GenericPool<Redis>
    cookielessRedisPool: GenericPool<Redis>
    kafka: Kafka
    kafkaProducer: KafkaProducerWrapper
    objectStorage?: ObjectStorage
    // currently enabled plugin status
    plugins: Map<PluginId, Plugin>
    pluginConfigs: Map<PluginConfigId, PluginConfig>
    pluginConfigsPerTeam: Map<TeamId, PluginConfig[]>
    pluginSchedule: Record<string, PluginConfigId[]> | null
    // unique hash for each plugin config; used to verify IDs caught on stack traces for unhandled promise rejections
    pluginConfigSecrets: Map<PluginConfigId, string>
    pluginConfigSecretLookup: Map<string, PluginConfigId>
    // tools
    teamManager: TeamManager
    teamSecretKeysManager: TeamSecretKeysManager
    pluginsApiKeyManager: PluginsApiKeyManager
    rootAccessManager: RootAccessManager
    actionManager: ActionManager
    actionManagerCDP: ActionManagerCDP
    actionMatcher: ActionMatcher
    appMetrics: AppMetrics
    rustyHook: RustyHook
    groupTypeManager: GroupTypeManager
    groupRepository: GroupRepository
    clickhouseGroupRepository: ClickhouseGroupRepository
    personRepository: PersonRepository
    celery: Celery
    // geoip database, setup in workers
    geoipService: GeoIPService
    // ValueMatchers used for various opt-in/out features
    pluginConfigsToSkipElementsParsing: ValueMatcher<number>
    // lookups
    eventsToDropByToken: Map<string, string[]>
    encryptedFields: EncryptedFields
    cookielessManager: CookielessManager
    pubSub: PubSub
    integrationManager: IntegrationManagerService
    quotaLimiting: QuotaLimiting
    internalCaptureService: InternalCaptureService
}

export interface PluginServerCapabilities {
    // Warning: when adding more entries, make sure to update worker/vm/capabilities.ts
    // and the shouldSetupPluginInServer() test accordingly.
    ingestionV2Combined?: boolean
    ingestionV2?: boolean
    logsIngestion?: boolean
    processAsyncWebhooksHandlers?: boolean
    sessionRecordingBlobIngestionV2?: boolean
    sessionRecordingBlobIngestionV2Overflow?: boolean
    cdpProcessedEvents?: boolean
    cdpPersonUpdates?: boolean
    cdpInternalEvents?: boolean
    cdpLegacyOnEvent?: boolean
    cdpCyclotronWorker?: boolean
    cdpCyclotronWorkerHogFlow?: boolean
    cdpCyclotronWorkerDelay?: boolean
    cdpBehaviouralEvents?: boolean
    cdpCohortMembership?: boolean
    cdpApi?: boolean
    appManagementSingleton?: boolean
    evaluationScheduler?: boolean
}

export interface EnqueuedPluginJob {
    type: string
    payload: Record<string, any>
    timestamp: number
    pluginConfigId: number
    pluginConfigTeam: number
    jobKey?: string
}

export type PluginId = Plugin['id']
export type PluginConfigId = PluginConfig['id']
export type TeamId = Team['id']
/**
 * An integer, just like team ID. In fact project ID = ID of its first team, the one was created along with the project.
 * A branded type here so that we don't accidentally pass a team ID as a project ID, or vice versa.
 */
export type ProjectId = Team['id'] & { __brand: 'ProjectId' }

export enum MetricMathOperations {
    Increment = 'increment',
    Max = 'max',
    Min = 'min',
}

export type StoredMetricMathOperations = 'max' | 'min' | 'sum'
export type StoredPluginMetrics = Record<string, StoredMetricMathOperations> | null
export type PluginMetricsVmResponse = Record<string, string> | null

export interface JobPayloadFieldOptions {
    type: 'string' | 'boolean' | 'json' | 'number' | 'date' | 'daterange'
    title?: string
    required?: boolean
    default?: any
    staff_only?: boolean
}

export interface JobSpec {
    payload?: Record<string, JobPayloadFieldOptions>
}

export interface Plugin {
    id: number
    organization_id?: string
    name: string
    plugin_type: 'local' | 'respository' | 'custom' | 'source' | 'inline'
    description?: string
    is_global: boolean
    is_preinstalled?: boolean
    url?: string
    config_schema?: Record<string, PluginConfigSchema> | PluginConfigSchema[]
    tag?: string
    /** Cached source for plugin.json from a joined PluginSourceFile query */
    source__plugin_json?: string
    /** Cached source for index.ts from a joined PluginSourceFile query */
    source__index_ts?: string
    /** Cached source for frontend.tsx from a joined PluginSourceFile query */
    source__frontend_tsx?: string
    /** Cached source for site.ts from a joined PluginSourceFile query */
    source__site_ts?: string
    error?: PluginError
    from_json?: boolean
    from_web?: boolean
    created_at?: string
    updated_at?: string
    capabilities?: PluginCapabilities
    metrics?: StoredPluginMetrics
    is_stateless?: boolean
    log_level?: PluginLogLevel
}

export interface PluginCapabilities {
    methods?: string[]
}

export enum PluginMethod {
    onEvent = 'onEvent',
    composeWebhook = 'composeWebhook',
}

export interface PluginConfig {
    id: number
    team_id: TeamId
    plugin?: Plugin
    plugin_id: PluginId
    enabled: boolean
    order: number
    config: Record<string, unknown>
    attachments?: Record<string, PluginAttachment>
    instance?: PluginInstance | null
    created_at: string
    updated_at?: string
    // We're migrating to a new functions that take PostHogEvent instead of PluginEvent
    // we'll need to know which method this plugin is using to call it the right way
    // undefined for old plugins with multiple or deprecated methods
    method?: PluginMethod
}

export interface PluginJsonConfig {
    name?: string
    description?: string
    url?: string
    main?: string
    lib?: string
    config?: Record<string, PluginConfigSchema> | PluginConfigSchema[]
}

export interface PluginError {
    message: string
    time: string
    name?: string
    stack?: string
    event?: PluginEvent | ProcessedPluginEvent | PostHogEvent | null
}

export interface PluginAttachmentDB {
    id: number
    team_id: TeamId | null
    plugin_config_id: PluginConfigId | null
    key: string
    content_type: string
    file_size: number | null
    file_name: string
    contents: Buffer | null
}

export enum PluginLogEntrySource {
    System = 'SYSTEM',
    Plugin = 'PLUGIN',
    Console = 'CONSOLE',
}

export enum PluginLogEntryType {
    Debug = 'DEBUG',
    Log = 'LOG',
    Info = 'INFO',
    Warn = 'WARN',
    Error = 'ERROR',
}

export enum PluginLogLevel {
    Full = 0, // all logs
    Log = 1, // all except debug
    Info = 2, // all expect log and debug
    Warn = 3, // all except log, debug and info
    Critical = 4, // only error type and system source
}

export enum CookielessServerHashMode {
    Disabled = 0,
    Stateless = 1,
    Stateful = 2,
}

export interface PluginLogEntry {
    id: string
    team_id: number
    plugin_id: number
    plugin_config_id: number
    timestamp: string
    source: PluginLogEntrySource
    type: PluginLogEntryType
    message: string
    instance_id: string
}

export type PluginMethods = {
    setupPlugin?: () => Promise<void>
    teardownPlugin?: () => Promise<void>
    getSettings?: () => PluginSettings
    onEvent?: (event: ProcessedPluginEvent) => Promise<void>
    composeWebhook?: (event: PostHogEvent) => Webhook | null
    processEvent?: (event: PluginEvent) => Promise<PluginEvent>
}

// Helper when ensuring that a required method is implemented
export type PluginMethodsConcrete = Required<PluginMethods>

export enum AlertLevel {
    P0 = 0,
    P1 = 1,
    P2 = 2,
    P3 = 3,
    P4 = 4,
}

export enum Service {
    PluginServer = 'plugin_server',
    DjangoServer = 'django_server',
    Redis = 'redis',
    Postgres = 'postgres',
    ClickHouse = 'clickhouse',
    Kafka = 'kafka',
}
export interface Alert {
    id: string
    level: AlertLevel
    key: string
    description?: string
    trigger_location: Service
}
export interface PluginConfigVMResponse {
    vm: VM
    methods: PluginMethods
    vmResponseVariable: string
    usedImports: Set<string>
}

export interface EventUsage {
    event: string
    usage_count: number | null
    volume: number | null
}

export interface PropertyUsage {
    key: string
    usage_count: number | null
    volume: number | null
}

export interface ProductFeature {
    key: string
    name: string
}

/** Raw Organization row from database. */
export interface RawOrganization {
    id: string
    name: string
    created_at: string
    updated_at: string
    available_product_features: ProductFeature[]
}

// NOTE: We don't need to list all options here - only the ones we use
export type OrganizationAvailableFeature = 'group_analytics' | 'data_pipelines' | 'zapier'

/** Usable Team model. */
export interface Team {
    id: number
    project_id: ProjectId
    uuid: string
    organization_id: string
    name: string
    anonymize_ips: boolean
    api_token: string
    slack_incoming_webhook: string | null
    session_recording_opt_in: boolean
    person_processing_opt_out: boolean | null
    heatmaps_opt_in: boolean | null
    ingested_event: boolean
    person_display_name_properties: string[] | null
    test_account_filters:
        | (EventPropertyFilter | PersonPropertyFilter | ElementPropertyFilter | CohortPropertyFilter)[]
        | null
    cookieless_server_hash_mode: CookielessServerHashMode | null
    timezone: string
    // This is parsed as a join from the org table
    available_features: OrganizationAvailableFeature[]
    drop_events_older_than_seconds: number | null
    verify_events?: 'accept_all' | 'reject_invalid' | 'reject_unverified'
}

/** Properties shared by RawEventMessage and EventMessage. */
export interface BaseEventMessage {
    distinct_id: string
    ip: string
    site_url: string
    team_id: number
    uuid: string
}

/** Raw event message as received via Kafka. */
export interface RawEventMessage extends BaseEventMessage {
    /** JSON-encoded object. */
    data: string
    /** ISO-formatted datetime. */
    now: string
    /** ISO-formatted datetime. May be empty! */
    sent_at: string
    /** JSON-encoded number. */
    kafka_offset: string
    /** Messages may have a token instead of a team_id, to be used e.g. to
     * resolve to a team_id */
    token?: string
}

/** Usable event message. */
export interface EventMessage extends BaseEventMessage {
    data: PluginEvent
    now: DateTime
    sent_at: DateTime | null
}

export enum JwtVerificationStatus {
    Verified = 'verified',
    Invalid = 'invalid',
    NotVerified = 'not_verified',
}

/** Properties shared by RawClickHouseEvent and ClickHouseEvent. */
interface BaseEvent {
    uuid: string
    event: string
    team_id: TeamId
    distinct_id: string
    /** Person UUID. */
    person_id?: string
    /** JWT verification status */
    verified?: JwtVerificationStatus
}

export type ISOTimestamp = Brand<string, 'ISOTimestamp'>
export type ClickHouseTimestamp = Brand<string, 'ClickHouseTimestamp'>
export type ClickHouseTimestampSecondPrecision = Brand<string, 'ClickHouseTimestamp'>
export type PersonMode = 'full' | 'propertyless' | 'force_upgrade'

/** Raw event row from ClickHouse. */
export interface RawClickHouseEvent extends BaseEvent {
    project_id: ProjectId
    timestamp: ClickHouseTimestamp
    created_at: ClickHouseTimestamp
    properties?: string
    elements_chain: string
    person_created_at?: ClickHouseTimestamp
    person_properties?: string
    group0_properties?: string
    group1_properties?: string
    group2_properties?: string
    group3_properties?: string
    group4_properties?: string
    group0_created_at?: ClickHouseTimestamp
    group1_created_at?: ClickHouseTimestamp
    group2_created_at?: ClickHouseTimestamp
    group3_created_at?: ClickHouseTimestamp
    group4_created_at?: ClickHouseTimestamp
    person_mode: PersonMode
}

export interface RawKafkaEvent extends RawClickHouseEvent {
    /**
     * The project ID field is only included in the `clickhouse_events_json` topic, not present in ClickHouse.
     * That's because we need it in `property-defs-rs` and not elsewhere.
     */
    project_id: ProjectId
}

/** Parsed event row from ClickHouse. */
export interface ClickHouseEvent extends BaseEvent {
    project_id: ProjectId
    timestamp: DateTime
    created_at: DateTime
    properties: Record<string, any>
    elements_chain: Element[] | null
    person_created_at: DateTime | null
    person_properties: Record<string, any>
    group0_properties: Record<string, any>
    group1_properties: Record<string, any>
    group2_properties: Record<string, any>
    group3_properties: Record<string, any>
    group4_properties: Record<string, any>
    group0_created_at?: DateTime | null
    group1_created_at?: DateTime | null
    group2_created_at?: DateTime | null
    group3_created_at?: DateTime | null
    group4_created_at?: DateTime | null
    person_mode: PersonMode
}

/** Event structure before initial ingestion.
 * This is what is used for all ingestion steps that run _before_ the clickhouse events topic.
 */
export interface PreIngestionEvent {
    eventUuid: string
    event: string
    teamId: TeamId
    projectId: ProjectId
    distinctId: string
    properties: Properties
    timestamp: ISOTimestamp
}

/** Parsed event structure after initial ingestion.
 * This is what is used for all ingestion steps that run _after_ the clickhouse events topic.
 */

export interface PostIngestionEvent extends PreIngestionEvent {
    elementsList?: Element[]
    person_id?: string // This is not optional, but BaseEvent needs to be fixed first
    person_created_at: ISOTimestamp | null
    person_properties: Properties

    groups?: Record<
        string,
        {
            key: string
            type: string
            index: number
            properties: Properties
        }
    >
}

export interface DeadLetterQueueEvent {
    id: string
    event_uuid: string
    event: string
    properties: string
    distinct_id: string
    team_id: number
    elements_chain: string
    created_at: string
    ip: string
    site_url: string
    now: string
    raw_payload: string
    error_timestamp: string
    error_location: string
    error: string
    tags: string[]
    _timestamp: string
    _offset: number
}

export type PropertiesLastUpdatedAt = Record<string, string>
export type PropertiesLastOperation = Record<string, PropertyUpdateOperation>

/** Properties shared by RawPerson and Person. */
export interface BasePerson {
    // NOTE: id is a bigint in the DB, which pg lib returns as a string
    // We leave it as a string as dealing with the bigint type is tricky and we don't need any of its features
    id: string
    team_id: number
    properties: Properties
    is_user_id: number | null
    is_identified: boolean
    uuid: string
    properties_last_updated_at: PropertiesLastUpdatedAt
    properties_last_operation: PropertiesLastOperation | null
}

/** Raw Person row from database. */
export interface RawPerson extends BasePerson {
    created_at: string
    version: string | null
}

/** Usable Person model. */
export interface InternalPerson extends BasePerson {
    created_at: DateTime
    version: number
}

/** Person model exposed outside of person-specific DB logic. */
export interface Person {
    team_id: number
    properties: Properties
    uuid: string
    created_at: DateTime

    // Set to `true` when an existing person row was found for this `distinct_id`, but the event was
    // sent with `$process_person_profile=false`. This is an unexpected branch that we want to flag
    // for debugging and billing purposes, and typically means a misconfigured SDK.
    force_upgrade?: boolean
}

/** Clickhouse Person model. */
export interface ClickHousePerson {
    id: string
    created_at: string
    team_id: number
    properties: string
    is_identified: number
    is_deleted: number
    timestamp: string
    version: number
}

export type GroupTypeIndex = 0 | 1 | 2 | 3 | 4

interface BaseGroup {
    id: number
    team_id: number
    group_type_index: GroupTypeIndex
    group_key: string
    group_properties: Properties
    properties_last_updated_at: PropertiesLastUpdatedAt
    properties_last_operation: PropertiesLastOperation
}

/** Raw Group row from database. */
export interface RawGroup extends BaseGroup {
    created_at: string
    version: string
}

/** Usable Group model. */
export interface Group extends BaseGroup {
    created_at: DateTime
    version: number
}

export type GroupKey = string
/** Clickhouse Group model */
export interface ClickhouseGroup {
    group_type_index: GroupTypeIndex
    group_key: GroupKey
    created_at: string
    team_id: number
    group_properties: string
}

/** Usable PersonDistinctId model. */
export interface PersonDistinctId {
    id: number
    team_id: number
    person_id: number
    distinct_id: string
    version: string | null
}

/** ClickHouse PersonDistinctId model. (person_distinct_id2 table) */
export interface ClickHousePersonDistinctId2 {
    team_id: number
    person_id: string
    distinct_id: string
    is_deleted: 0 | 1
    version: number
}

/** Usable Cohort model. */
export interface Cohort {
    id: number
    name: string
    description: string
    deleted: boolean
    groups: any[]
    team_id: Team['id']
    created_at: string
    created_by_id: number
    is_calculating: boolean
    last_calculation: string
    errors_calculating: number
    is_static: boolean
    version: number | null
    pending_version: number
}

/** Usable CohortPeople model. */
export interface CohortPeople {
    id: number
    cohort_id: number
    person_id: number
}

/** Usable Hook model. */
export interface Hook {
    id: string
    team_id: number
    user_id: number
    resource_id: number | null
    event: string
    target: string
    created: string
    updated: string
}

/** Sync with posthog/frontend/src/types.ts */
export enum PropertyOperator {
    Exact = 'exact',
    IsNot = 'is_not',
    IContains = 'icontains',
    NotIContains = 'not_icontains',
    Regex = 'regex',
    NotRegex = 'not_regex',
    GreaterThan = 'gt',
    LessThan = 'lt',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
    IsDateBefore = 'is_date_before',
    IsDateAfter = 'is_date_after',
    IsCleanedPathExact = 'is_cleaned_path_exact',
}

/** Sync with posthog/frontend/src/types.ts */
interface PropertyFilterBase {
    key: string
    value?: string | number | Array<string | number> | null
    label?: string
}

/** Sync with posthog/frontend/src/types.ts */
export interface PropertyFilterWithOperator extends PropertyFilterBase {
    operator?: PropertyOperator
}

/** Sync with posthog/frontend/src/types.ts */
export interface EventPropertyFilter extends PropertyFilterWithOperator {
    type: 'event'
}

/** Sync with posthog/frontend/src/types.ts */
export interface HogQLPropertyFilter extends PropertyFilterWithOperator {
    type: 'hogql'
}

/** Sync with posthog/frontend/src/types.ts */
export interface PersonPropertyFilter extends PropertyFilterWithOperator {
    type: 'person'
}

export interface DataWarehousePropertyFilter extends PropertyFilterWithOperator {
    type: 'data_warehouse'
}

export interface DataWarehousePersonPropertyFilter extends PropertyFilterWithOperator {
    type: 'data_warehouse_person_property'
}

/** Sync with posthog/frontend/src/types.ts */
export interface ElementPropertyFilter extends PropertyFilterWithOperator {
    type: 'element'
    key: 'tag_name' | 'text' | 'href' | 'selector'
    value: string | string[]
}

/** Sync with posthog/frontend/src/types.ts */
export interface CohortPropertyFilter extends PropertyFilterBase {
    type: 'cohort'
    key: 'id'
    value: number | string
}

/** Sync with posthog/frontend/src/types.ts */
export type PropertyFilter =
    | EventPropertyFilter
    | PersonPropertyFilter
    | ElementPropertyFilter
    | CohortPropertyFilter
    | DataWarehousePropertyFilter
    | DataWarehousePersonPropertyFilter
    | HogQLPropertyFilter

/** Sync with posthog/frontend/src/types.ts */
export enum StringMatching {
    Contains = 'contains',
    Regex = 'regex',
    Exact = 'exact',
}

export interface ActionStep {
    tag_name: string | null
    text: string | null
    /** @default StringMatching.Exact */
    text_matching: StringMatching | null
    href: string | null
    /** @default StringMatching.Exact */
    href_matching: StringMatching | null
    selector: string | null
    url: string | null
    /** @default StringMatching.Contains */
    url_matching: StringMatching | null
    event: string | null
    properties: PropertyFilter[] | null
}

/** Raw Action row from database. */
export interface RawAction {
    id: number
    team_id: TeamId
    name: string | null
    description: string
    created_at: string
    created_by_id: number | null
    deleted: boolean
    post_to_slack: boolean
    slack_message_format: string
    is_calculating: boolean
    updated_at: string
    last_calculated_at: string
    steps_json: ActionStep[] | null
}

/** Usable Action model. */
export interface Action extends Omit<RawAction, 'steps_json'> {
    steps: ActionStep[]
    hooks: Hook[]
}

/** Raw session recording event row from ClickHouse. */
export interface RawSessionRecordingEvent {
    uuid: string
    timestamp: string
    team_id: number
    distinct_id: string
    session_id: string
    window_id: string
    snapshot_data: string
    created_at: string
}

/** Raw session replay event row from ClickHouse. */
export interface RawSessionReplayEvent {
    min_first_timestamp: string
    team_id: number
    distinct_id: string
    session_id: string
    /* TODO what columns do we need */
}

export enum TimestampFormat {
    ClickHouseSecondPrecision = 'clickhouse-second-precision',
    ClickHouse = 'clickhouse',
    ISO = 'iso',
}

export interface PluginScheduleControl {
    stopSchedule: () => Promise<void>
    reloadSchedule: () => Promise<void>
}

export interface JobsConsumerControl {
    stop: () => Promise<void>
    resume: () => Promise<void>
}

export type IngestEventResponse =
    | { success: true; actionMatches: Action[]; preIngestionEvent: PreIngestionEvent | null }
    | { success: false; error: string }

export enum UnixTimestampPropertyTypeFormat {
    UNIX_TIMESTAMP = 'unix_timestamp',
    UNIX_TIMESTAMP_MILLISECONDS = 'unix_timestamp_milliseconds',
}

export enum DateTimePropertyTypeFormat {
    ISO8601_DATE = 'YYYY-MM-DDThh:mm:ssZ',
    FULL_DATE = 'YYYY-MM-DD hh:mm:ss',
    FULL_DATE_INCREASING = 'DD-MM-YYYY hh:mm:ss',
    DATE = 'YYYY-MM-DD',
    RFC_822 = 'rfc_822',
    WITH_SLASHES = 'YYYY/MM/DD hh:mm:ss',
    WITH_SLASHES_INCREASING = 'DD/MM/YYYY hh:mm:ss',
}

export enum PropertyType {
    DateTime = 'DateTime',
    String = 'String',
    Numeric = 'Numeric',
    Boolean = 'Boolean',
}

export enum PropertyDefinitionTypeEnum {
    Event = 1,
    Person = 2,
    Group = 3,
    Session = 4,
}

export type ResolvedGroups = Record<string, number>

export interface PropertyDefinitionType {
    id: string
    name: string
    is_numerical: boolean
    team_id: number
    project_id: number | null
    property_type: PropertyType | null
    type: PropertyDefinitionTypeEnum
    group_type_name?: string
    group_type_index?: number | null
    volume_30_day?: number | null
    query_usage_30_day?: number | null
}

export interface EventPropertyType {
    id: string
    event: string
    property: string
    team_id: number
    project_id: number | null
}

export type GroupTypeToColumnIndex = Record<string, GroupTypeIndex>

export enum PropertyUpdateOperation {
    Set = 'set',
    SetOnce = 'set_once',
}

export type StatelessInstanceMap = Record<PluginId, PluginInstance>

export enum OrganizationPluginsAccessLevel {
    NONE = 0,
    CONFIG = 3,
    INSTALL = 6,
    ROOT = 9,
}

export enum OrganizationMembershipLevel {
    Member = 1,
    Admin = 8,
    Owner = 15,
}

export interface PipelineEvent extends Omit<PluginEvent, 'team_id'> {
    team_id?: number | null
    token?: string
}

export interface EventHeaders {
    token?: string
    distinct_id?: string
    timestamp?: string
    event?: string
    uuid?: string
    jwt?: string
    force_disable_person_processing: boolean
}

export interface IncomingEvent {
    event: PipelineEvent
    headers?: EventHeaders
}

export interface IncomingEventWithTeam {
    message: Message
    event: PipelineEvent
    team: Team
    headers: EventHeaders
}

export type RedisPool = GenericPool<Redis>

export type RRWebEvent = Record<string, any> & {
    timestamp: number
    type: number
    data: any
}

export interface ValueMatcher<T> {
    (value: T): boolean
}

export type RawClickhouseHeatmapEvent = {
    /**
     * session id lets us offer example recordings on high traffic parts of the page,
     * and could let us offer more advanced filtering of heatmap data
     * we will break the relationship between particular sessions and clicks in aggregating this data
     * it should always be treated as an exemplar and not as concrete values
     */
    session_id: string
    distinct_id: string
    viewport_width: number
    viewport_height: number
    pointer_target_fixed: boolean
    current_url: string
    // x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x: number
    // y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y: number
    scale_factor: 16 // in the future we may support other values
    timestamp: string
    type: string
    team_id: number
}

export interface CdpPersonPerformedEvent {
    teamId: number
    personId: string
    eventName: string
}

export interface HookPayload {
    hook: Pick<Hook, 'id' | 'event' | 'target'>

    data: {
        eventUuid: string
        event: string
        teamId: TeamId
        distinctId: string
        properties: Properties
        timestamp: ISOTimestamp
        elementsList?: Element[]

        person: {
            uuid: string
            properties: Properties
            created_at: ISOTimestamp | null
        }
    }
}

/**
 * Metadata switchover can be absent, enforced (boolean true), or after a provided date
 */
export type SessionRecordingV2MetadataSwitchoverDate = Date | null | true
