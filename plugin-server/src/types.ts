import { ReaderModel } from '@maxmind/geoip2-node'
import ClickHouse from '@posthog/clickhouse'
import {
    Element,
    Meta,
    PluginAttachment,
    PluginConfigSchema,
    PluginEvent,
    PluginSettings,
    ProcessedPluginEvent,
    Properties,
} from '@posthog/plugin-scaffold'
import { Pool as GenericPool } from 'generic-pool'
import { StatsD } from 'hot-shots'
import { Redis } from 'ioredis'
import { Kafka } from 'kafkajs'
import { DateTime } from 'luxon'
import { Job } from 'node-schedule'
import { VM } from 'vm2'

import { ObjectStorage } from './main/services/object_storage'
import { DB } from './utils/db/db'
import { KafkaProducerWrapper } from './utils/db/kafka-producer-wrapper'
import { PostgresRouter } from './utils/db/postgres'
import { UUID } from './utils/utils'
import { AppMetrics } from './worker/ingestion/app-metrics'
import { EventPipelineResult } from './worker/ingestion/event-pipeline/runner'
import { OrganizationManager } from './worker/ingestion/organization-manager'
import { EventsProcessor } from './worker/ingestion/process-event'
import { TeamManager } from './worker/ingestion/team-manager'
import { PluginsApiKeyManager } from './worker/vm/extensions/helpers/api-key-manager'
import { RootAccessManager } from './worker/vm/extensions/helpers/root-acess-manager'
import { LazyPluginVM } from './worker/vm/lazy'
import { PromiseManager } from './worker/vm/promise-manager'

export { Element } from '@posthog/plugin-scaffold' // Re-export Element from scaffolding, for backwards compat.

type Brand<K, T> = K & { __brand: T }

export enum LogLevel {
    None = 'none',
    Debug = 'debug',
    Info = 'info',
    Log = 'log',
    Warn = 'warn',
    Error = 'error',
}

export const logLevelToNumber: Record<LogLevel, number> = {
    [LogLevel.None]: 0,
    [LogLevel.Debug]: 10,
    [LogLevel.Info]: 20,
    [LogLevel.Log]: 30,
    [LogLevel.Warn]: 40,
    [LogLevel.Error]: 50,
}

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
    ingestion = 'ingestion',
    ingestion_overflow = 'ingestion-overflow',
    ingestion_historical = 'ingestion-historical',
    async_onevent = 'async-onevent',
    async_webhooks = 'async-webhooks',
    jobs = 'jobs',
    scheduler = 'scheduler',
    analytics_ingestion = 'analytics-ingestion',
    recordings_ingestion = 'recordings-ingestion',
    recordings_blob_ingestion = 'recordings-blob-ingestion',
}

export const stringToPluginServerMode = Object.fromEntries(
    Object.entries(PluginServerMode).map(([key, value]) => [
        value,
        PluginServerMode[key as keyof typeof PluginServerMode],
    ])
) as Record<string, PluginServerMode>

export interface PluginsServerConfig {
    WORKER_CONCURRENCY: number // number of concurrent worker threads
    TASKS_PER_WORKER: number // number of parallel tasks per worker thread
    INGESTION_CONCURRENCY: number // number of parallel event ingestion queues per batch
    INGESTION_BATCH_SIZE: number // kafka consumer batch size
    TASK_TIMEOUT: number // how many seconds until tasks are timed out
    DATABASE_URL: string // Postgres database URL
    DATABASE_READONLY_URL: string // Optional read-only replica to the main Postgres database
    PLUGIN_STORAGE_DATABASE_URL: string // Optional read-write Postgres database for plugin storage
    POSTGRES_CONNECTION_POOL_SIZE: number
    POSTHOG_DB_NAME: string | null
    POSTHOG_DB_USER: string
    POSTHOG_DB_PASSWORD: string
    POSTHOG_POSTGRES_HOST: string
    POSTHOG_POSTGRES_PORT: number
    CLICKHOUSE_HOST: string
    CLICKHOUSE_OFFLINE_CLUSTER_HOST: string | null
    CLICKHOUSE_DATABASE: string
    CLICKHOUSE_USER: string
    CLICKHOUSE_PASSWORD: string | null
    CLICKHOUSE_CA: string | null // ClickHouse CA certs
    CLICKHOUSE_SECURE: boolean // whether to secure ClickHouse connection
    CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS: boolean // whether to disallow external schemas like protobuf for clickhouse kafka engine
    CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS_TEAMS: string // (advanced) a comma separated list of teams to disable clickhouse external schemas for
    CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: string // (advanced) topic to send events to for clickhouse ingestion
    REDIS_URL: string
    POSTHOG_REDIS_PASSWORD: string
    POSTHOG_REDIS_HOST: string
    POSTHOG_REDIS_PORT: number
    REDIS_POOL_MIN_SIZE: number // minimum number of Redis connections to use per thread
    REDIS_POOL_MAX_SIZE: number // maximum number of Redis connections to use per thread
    KAFKA_HOSTS: string // comma-delimited Kafka hosts
    KAFKA_CLIENT_CERT_B64: string | undefined
    KAFKA_CLIENT_CERT_KEY_B64: string | undefined
    KAFKA_TRUSTED_CERT_B64: string | undefined
    KAFKA_SECURITY_PROTOCOL: KafkaSecurityProtocol | undefined
    KAFKA_SASL_MECHANISM: KafkaSaslMechanism | undefined
    KAFKA_SASL_USER: string | undefined
    KAFKA_SASL_PASSWORD: string | undefined
    KAFKA_CLIENT_RACK: string | undefined
    KAFKA_CONSUMPTION_USE_RDKAFKA: boolean
    KAFKA_CONSUMPTION_RDKAFKA_COOPERATIVE_REBALANCE: boolean
    KAFKA_CONSUMPTION_MAX_BYTES: number
    KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION: number
    KAFKA_CONSUMPTION_MAX_WAIT_MS: number // fetch.wait.max.ms rdkafka parameter
    KAFKA_CONSUMPTION_ERROR_BACKOFF_MS: number // fetch.error.backoff.ms rdkafka parameter
    KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS: number
    KAFKA_CONSUMPTION_TOPIC: string | null
    KAFKA_CONSUMPTION_OVERFLOW_TOPIC: string | null
    KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS: number | null
    KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS: number
    KAFKA_TOPIC_CREATION_TIMEOUT_MS: number
    KAFKA_PRODUCER_MAX_QUEUE_SIZE: number
    KAFKA_PRODUCER_WAIT_FOR_ACK: boolean
    KAFKA_MAX_MESSAGE_BATCH_SIZE: number
    KAFKA_FLUSH_FREQUENCY_MS: number
    APP_METRICS_FLUSH_FREQUENCY_MS: number
    APP_METRICS_FLUSH_MAX_QUEUE_SIZE: number
    BASE_DIR: string // base path for resolving local plugins
    PLUGINS_RELOAD_PUBSUB_CHANNEL: string // Redis channel for reload events'
    LOG_LEVEL: LogLevel
    SENTRY_DSN: string | null
    SENTRY_PLUGIN_SERVER_TRACING_SAMPLE_RATE: number // Rate of tracing in plugin server (between 0 and 1)
    SENTRY_PLUGIN_SERVER_PROFILING_SAMPLE_RATE: number // Rate of profiling in plugin server (between 0 and 1)
    HTTP_SERVER_PORT: number
    STATSD_HOST: string | null
    STATSD_PORT: number
    STATSD_PREFIX: string
    SCHEDULE_LOCK_TTL: number // how many seconds to hold the lock for the schedule
    DISABLE_MMDB: boolean // whether to disable fetching MaxMind database for IP location
    DISTINCT_ID_LRU_SIZE: number
    EVENT_PROPERTY_LRU_SIZE: number // size of the event property tracker's LRU cache (keyed by [team.id, event])
    JOB_QUEUES: string // retry queue engine and fallback queues
    JOB_QUEUE_GRAPHILE_URL: string // use a different postgres connection in the graphile worker
    JOB_QUEUE_GRAPHILE_SCHEMA: string // the postgres schema that the graphile worker
    JOB_QUEUE_GRAPHILE_PREPARED_STATEMENTS: boolean // enable this to increase job queue throughput if not using pgbouncer
    JOB_QUEUE_GRAPHILE_CONCURRENCY: number // concurrent jobs per pod
    JOB_QUEUE_S3_AWS_ACCESS_KEY: string
    JOB_QUEUE_S3_AWS_SECRET_ACCESS_KEY: string
    JOB_QUEUE_S3_AWS_REGION: string
    JOB_QUEUE_S3_BUCKET_NAME: string
    JOB_QUEUE_S3_PREFIX: string // S3 filename prefix for the S3 job queue
    CRASH_IF_NO_PERSISTENT_JOB_QUEUE: boolean // refuse to start unless there is a properly configured persistent job queue (e.g. graphile)
    HEALTHCHECK_MAX_STALE_SECONDS: number // maximum number of seconds the plugin server can go without ingesting events before the healthcheck fails
    PISCINA_USE_ATOMICS: boolean // corresponds to the piscina useAtomics config option (https://github.com/piscinajs/piscina#constructor-new-piscinaoptions)
    PISCINA_ATOMICS_TIMEOUT: number // (advanced) corresponds to the length of time a piscina worker should block for when looking for tasks
    SITE_URL: string | null
    MAX_PENDING_PROMISES_PER_WORKER: number // (advanced) maximum number of promises that a worker can have running at once in the background. currently only targets the exportEvents buffer.
    KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY: number // (advanced) how many kafka partitions the plugin server should consume from concurrently
    RECORDING_PARTITIONS_CONSUMED_CONCURRENTLY: number
    CONVERSION_BUFFER_ENABLED: boolean
    CONVERSION_BUFFER_ENABLED_TEAMS: string
    CONVERSION_BUFFER_TOPIC_ENABLED_TEAMS: string
    BUFFER_CONVERSION_SECONDS: number
    FETCH_HOSTNAME_GUARD_TEAMS: string
    PERSON_INFO_CACHE_TTL: number
    KAFKA_HEALTHCHECK_SECONDS: number
    OBJECT_STORAGE_ENABLED: boolean // Disables or enables the use of object storage. It will become mandatory to use object storage
    OBJECT_STORAGE_REGION: string // s3 region
    OBJECT_STORAGE_ENDPOINT: string // s3 endpoint
    OBJECT_STORAGE_ACCESS_KEY_ID: string
    OBJECT_STORAGE_SECRET_ACCESS_KEY: string
    OBJECT_STORAGE_BUCKET: string // the object storage bucket name
    PLUGIN_SERVER_MODE: PluginServerMode | null
    PLUGIN_LOAD_SEQUENTIALLY: boolean // could help with reducing memory usage spikes on startup
    KAFKAJS_LOG_LEVEL: 'NOTHING' | 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'
    HISTORICAL_EXPORTS_ENABLED: boolean // enables historical exports for export apps
    HISTORICAL_EXPORTS_MAX_RETRY_COUNT: number
    HISTORICAL_EXPORTS_INITIAL_FETCH_TIME_WINDOW: number
    HISTORICAL_EXPORTS_FETCH_WINDOW_MULTIPLIER: number
    APP_METRICS_GATHERED_FOR_ALL: boolean // whether to gather app metrics for all teams
    MAX_TEAM_ID_TO_BUFFER_ANONYMOUS_EVENTS_FOR: number
    USE_KAFKA_FOR_SCHEDULED_TASKS: boolean // distribute scheduled tasks across the scheduler workers
    EVENT_OVERFLOW_BUCKET_CAPACITY: number
    EVENT_OVERFLOW_BUCKET_REPLENISH_RATE: number
    /** Label of the PostHog Cloud environment. Null if not running PostHog Cloud. @example 'US' */
    CLOUD_DEPLOYMENT: string | null

    // dump profiles to disk, covering the first N seconds of runtime
    STARTUP_PROFILE_DURATION_SECONDS: number
    STARTUP_PROFILE_CPU: boolean
    STARTUP_PROFILE_HEAP: boolean
    STARTUP_PROFILE_HEAP_INTERVAL: number
    STARTUP_PROFILE_HEAP_DEPTH: number

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

    // Dedicated infra values
    SESSION_RECORDING_KAFKA_HOSTS: string | undefined
    SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL: KafkaSecurityProtocol | undefined
    SESSION_RECORDING_KAFKA_BATCH_SIZE: number
    SESSION_RECORDING_KAFKA_QUEUE_SIZE: number
    POSTHOG_SESSION_RECORDING_REDIS_HOST: string | undefined
    POSTHOG_SESSION_RECORDING_REDIS_PORT: number | undefined
}

export interface Hub extends PluginsServerConfig {
    instanceId: UUID
    // what tasks this server will tackle - e.g. ingestion, scheduled plugins or others.
    capabilities: PluginServerCapabilities
    // active connections to Postgres, Redis, ClickHouse, Kafka, StatsD
    db: DB
    postgres: PostgresRouter
    redisPool: GenericPool<Redis>
    clickhouse: ClickHouse
    kafka: Kafka
    kafkaProducer: KafkaProducerWrapper
    objectStorage: ObjectStorage
    // metrics
    statsd?: StatsD
    pluginMetricsJob: Job | undefined
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
    organizationManager: OrganizationManager
    pluginsApiKeyManager: PluginsApiKeyManager
    rootAccessManager: RootAccessManager
    promiseManager: PromiseManager
    eventsProcessor: EventsProcessor
    appMetrics: AppMetrics
    // geoip database, setup in workers
    mmdb?: ReaderModel
    // diagnostics
    lastActivity: number
    lastActivityType: string
    statelessVms: StatelessVmMap
    conversionBufferEnabledTeams: Set<number>
    /** null means that the hostname guard is enabled for everyone */
    fetchHostnameGuardTeams: Set<number> | null
    // functions
    enqueuePluginJob: (job: EnqueuedPluginJob) => Promise<void>
    // ValueMatchers used for various opt-in/out features
    pluginConfigsToSkipElementsParsing: ValueMatcher<number>
}

export interface PluginServerCapabilities {
    // Warning: when adding more entries, make sure to update worker/vm/capabilities.ts
    // and the shouldSetupPluginInServer() test accordingly.
    ingestion?: boolean
    ingestionOverflow?: boolean
    ingestionHistorical?: boolean
    pluginScheduledTasks?: boolean
    processPluginJobs?: boolean
    processAsyncOnEventHandlers?: boolean
    processAsyncWebhooksHandlers?: boolean
    sessionRecordingIngestion?: boolean
    sessionRecordingBlobIngestion?: boolean
    transpileFrontendApps?: boolean // TODO: move this away from pod startup, into a graphile job
    preflightSchedules?: boolean // Used for instance health checks on hobby deploy, not useful on cloud
    http?: boolean
    mmdb?: boolean
}

export type EnqueuedJob = EnqueuedPluginJob | GraphileWorkerCronScheduleJob
export interface EnqueuedPluginJob {
    type: string
    payload: Record<string, any>
    timestamp: number
    pluginConfigId: number
    pluginConfigTeam: number
    jobKey?: string
}

export interface GraphileWorkerCronScheduleJob {
    timestamp?: number
    jobKey?: string
}

export enum JobName {
    PLUGIN_JOB = 'pluginJob',
    BUFFER_JOB = 'bufferJob',
}

export type PluginId = Plugin['id']
export type PluginConfigId = PluginConfig['id']
export type TeamId = Team['id']

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
    organization_id: string
    name: string
    plugin_type: 'local' | 'respository' | 'custom' | 'source'
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
    public_jobs?: Record<string, JobSpec>
    log_level?: PluginLogLevel
}

export interface PluginCapabilities {
    jobs?: string[]
    scheduled_tasks?: string[]
    methods?: string[]
}

export interface PluginConfig {
    id: number
    team_id: TeamId
    plugin?: Plugin
    plugin_id: PluginId
    enabled: boolean
    order: number
    config: Record<string, unknown>
    has_error: boolean
    attachments?: Record<string, PluginAttachment>
    vm?: LazyPluginVM | null
    created_at: string
    updated_at?: string
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
    event?: PluginEvent | ProcessedPluginEvent | null
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
    Debug = 1, // all except log
    Warn = 2, // all except log and info
    Critical = 3, // only error type and system source
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

export enum PluginSourceFileStatus {
    Transpiled = 'TRANSPILED',
    Locked = 'LOCKED',
    Error = 'ERROR',
}

export enum PluginTaskType {
    Job = 'job',
    Schedule = 'schedule',
}

export interface PluginTask {
    name: string
    type: PluginTaskType
    exec: (payload?: Record<string, any>) => Promise<any>

    __ignoreForAppMetrics?: boolean
}

export type WorkerMethods = {
    runAppsOnEventPipeline: (event: PostIngestionEvent) => Promise<void>
    runEventPipeline: (event: PipelineEvent) => Promise<EventPipelineResult>
}

export type VMMethods = {
    setupPlugin?: () => Promise<void>
    teardownPlugin?: () => Promise<void>
    getSettings?: () => PluginSettings
    onEvent?: (event: ProcessedPluginEvent) => Promise<void>
    exportEvents?: (events: PluginEvent[]) => Promise<void>
    processEvent?: (event: PluginEvent) => Promise<PluginEvent>
}

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
    methods: VMMethods
    tasks: Record<PluginTaskType, Record<string, PluginTask>>
    vmResponseVariable: string
}

export interface PluginConfigVMInternalResponse<M extends Meta = Meta> {
    methods: VMMethods
    tasks: Record<PluginTaskType, Record<string, PluginTask>>
    meta: M
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

/** Raw Organization row from database. */
export interface RawOrganization {
    id: string
    name: string
    created_at: string
    updated_at: string
    available_features: string[]
}

/** Usable Team model. */
export interface Team {
    id: number
    uuid: string
    organization_id: string
    name: string
    anonymize_ips: boolean
    api_token: string
    slack_incoming_webhook: string | null
    session_recording_opt_in: boolean
    ingested_event: boolean
    person_display_name_properties: string[] | null
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

/** Properties shared by RawClickHouseEvent and ClickHouseEvent. */
interface BaseEvent {
    uuid: string
    event: string
    team_id: number
    distinct_id: string
    /** Person UUID. */
    person_id?: string
}

export type ISOTimestamp = Brand<string, 'ISOTimestamp'>
export type ClickHouseTimestamp = Brand<string, 'ClickHouseTimestamp'>
export type ClickHouseTimestampSecondPrecision = Brand<string, 'ClickHouseTimestamp'>

/** Raw event row from ClickHouse. */
export interface RawClickHouseEvent extends BaseEvent {
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
}

/** Parsed event row from ClickHouse. */
export interface ClickHouseEvent extends BaseEvent {
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
}

/** Event in a database-agnostic shape, AKA an ingestion event.
 * This is what should be passed around most of the time in the plugin server.
 */
interface BaseIngestionEvent {
    eventUuid: string
    event: string
    ip: string | null
    teamId: TeamId
    distinctId: string
    properties: Properties
    timestamp: ISOTimestamp
    elementsList: Element[]
}

/** Ingestion event before saving, currently just an alias of BaseIngestionEvent. */
export type PreIngestionEvent = BaseIngestionEvent

/** Ingestion event after saving, currently just an alias of BaseIngestionEvent */
export interface PostIngestionEvent extends BaseIngestionEvent {
    person_id?: string // This is not optional, but BaseEvent needs to be fixed first
    person_created_at: ISOTimestamp | null
    person_properties: Properties
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
    id: number
    team_id: number
    properties: Properties
    is_user_id: number
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
export interface Person extends BasePerson {
    created_at: DateTime
    version: number
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
export interface PersonPropertyFilter extends PropertyFilterWithOperator {
    type: 'person'
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
export type PropertyFilter = EventPropertyFilter | PersonPropertyFilter | ElementPropertyFilter | CohortPropertyFilter

/** Sync with posthog/frontend/src/types.ts */
export enum StringMatching {
    Contains = 'contains',
    Regex = 'regex',
    Exact = 'exact',
}

export interface ActionStep {
    id: number
    action_id: number
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
    name: string | null
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
    bytecode?: any[]
    bytecode_error?: string
}

/** Usable Action model. */
export interface Action extends RawAction {
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

export interface RawPerformanceEvent {
    uuid: string
    team_id: number
    distinct_id: string
    session_id: string
    window_id: string
    pageview_id: string
    current_url: string

    // BASE_EVENT_COLUMNS
    time_origin: number
    timestamp: string
    entry_type: string
    name: string

    // RESOURCE_EVENT_COLUMNS
    start_time: number
    redirect_start: number
    redirect_end: number
    worker_start: number
    fetch_start: number
    domain_lookup_start: number
    domain_lookup_end: number
    connect_start: number
    secure_connection_start: number
    connect_end: number
    request_start: number
    response_start: number
    response_end: number
    decoded_body_size: number
    encoded_body_size: number
    duration: number

    initiator_type: string
    next_hop_protocol: string
    render_blocking_status: string
    response_status: number
    transfer_size: number

    // LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS
    largest_contentful_paint_element: string
    largest_contentful_paint_render_time: number
    largest_contentful_paint_load_time: number
    largest_contentful_paint_size: number
    largest_contentful_paint_id: string
    largest_contentful_paint_url: string

    // NAVIGATION_EVENT_COLUMNS
    dom_complete: number
    dom_content_loaded_event: number
    dom_interactive: number
    load_event_end: number
    load_event_start: number
    redirect_count: number
    navigation_type: string
    unload_event_end: number
    unload_event_start: number
}

export const PerformanceEventReverseMapping: { [key: number]: keyof RawPerformanceEvent } = {
    // BASE_PERFORMANCE_EVENT_COLUMNS
    0: 'entry_type',
    1: 'time_origin',
    2: 'name',

    // RESOURCE_EVENT_COLUMNS
    3: 'start_time',
    4: 'redirect_start',
    5: 'redirect_end',
    6: 'worker_start',
    7: 'fetch_start',
    8: 'domain_lookup_start',
    9: 'domain_lookup_end',
    10: 'connect_start',
    11: 'secure_connection_start',
    12: 'connect_end',
    13: 'request_start',
    14: 'response_start',
    15: 'response_end',
    16: 'decoded_body_size',
    17: 'encoded_body_size',
    18: 'initiator_type',
    19: 'next_hop_protocol',
    20: 'render_blocking_status',
    21: 'response_status',
    22: 'transfer_size',

    // LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS
    23: 'largest_contentful_paint_element',
    24: 'largest_contentful_paint_render_time',
    25: 'largest_contentful_paint_load_time',
    26: 'largest_contentful_paint_size',
    27: 'largest_contentful_paint_id',
    28: 'largest_contentful_paint_url',

    // NAVIGATION_EVENT_COLUMNS
    29: 'dom_complete',
    30: 'dom_content_loaded_event',
    31: 'dom_interactive',
    32: 'load_event_end',
    33: 'load_event_start',
    34: 'redirect_count',
    35: 'navigation_type',
    36: 'unload_event_end',
    37: 'unload_event_start',

    // Added after v1
    39: 'duration',
    40: 'timestamp',
}

export enum TimestampFormat {
    ClickHouseSecondPrecision = 'clickhouse-second-precision',
    ClickHouse = 'clickhouse',
    ISO = 'iso',
}

export enum Database {
    ClickHouse = 'clickhouse',
    Postgres = 'postgres',
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

export interface EventDefinitionType {
    id: string
    name: string
    volume_30_day: number | null
    query_usage_30_day: number | null
    team_id: number
    last_seen_at: string // DateTime
    created_at: string // DateTime
}

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
}

export interface PropertyDefinitionType {
    id: string
    name: string
    is_numerical: boolean
    volume_30_day: number | null
    query_usage_30_day: number | null
    team_id: number
    property_type?: PropertyType
    type: PropertyDefinitionTypeEnum
    group_type_index: number | null
}

export interface EventPropertyType {
    id: string
    event: string
    property: string
    team_id: number
}

export type PluginFunction = 'onEvent' | 'processEvent' | 'pluginTask'

export type GroupTypeToColumnIndex = Record<string, GroupTypeIndex>

export enum PropertyUpdateOperation {
    Set = 'set',
    SetOnce = 'set_once',
}

export type StatelessVmMap = Record<PluginId, LazyPluginVM>

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

export type RedisPool = GenericPool<Redis>

export type RRWebEvent = Record<string, any> & {
    timestamp: number
    type: number
    data: any
}

export interface ValueMatcher<T> {
    (value: T): boolean
}
