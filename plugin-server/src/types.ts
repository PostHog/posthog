import ClickHouse from '@posthog/clickhouse'
import {
    Meta,
    PluginAttachment,
    PluginConfigSchema,
    PluginEvent,
    ProcessedPluginEvent,
    Properties,
} from '@posthog/plugin-scaffold'
import { Pool as GenericPool } from 'generic-pool'
import { StatsD } from 'hot-shots'
import { Redis } from 'ioredis'
import { Kafka } from 'kafkajs'
import { DateTime } from 'luxon'
import { JobQueueManager } from 'main/job-queues/job-queue-manager'
import { Job } from 'node-schedule'
import { Pool } from 'pg'
import { VM } from 'vm2'

import { ObjectStorage } from './main/services/object_storage'
import { DB } from './utils/db/db'
import { KafkaProducerWrapper } from './utils/db/kafka-producer-wrapper'
import { InternalMetrics } from './utils/internal-metrics'
import { UUID } from './utils/utils'
import { ActionManager } from './worker/ingestion/action-manager'
import { ActionMatcher } from './worker/ingestion/action-matcher'
import { HookCommander } from './worker/ingestion/hooks'
import { OrganizationManager } from './worker/ingestion/organization-manager'
import { EventsProcessor } from './worker/ingestion/process-event'
import { SiteUrlManager } from './worker/ingestion/site-url-manager'
import { TeamManager } from './worker/ingestion/team-manager'
import { PluginsApiKeyManager } from './worker/vm/extensions/helpers/api-key-manager'
import { RootAccessManager } from './worker/vm/extensions/helpers/root-acess-manager'
import { LazyPluginVM } from './worker/vm/lazy'
import { PromiseManager } from './worker/vm/promise-manager'

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

export interface PluginsServerConfig extends Record<string, any> {
    WORKER_CONCURRENCY: number
    TASKS_PER_WORKER: number
    TASK_TIMEOUT: number
    DATABASE_URL: string | null
    POSTHOG_DB_NAME: string | null
    POSTHOG_DB_USER: string
    POSTHOG_DB_PASSWORD: string
    POSTHOG_POSTGRES_HOST: string
    POSTHOG_POSTGRES_PORT: number
    CLICKHOUSE_HOST: string
    CLICKHOUSE_DATABASE: string
    CLICKHOUSE_USER: string
    CLICKHOUSE_PASSWORD: string | null
    CLICKHOUSE_CA: string | null
    CLICKHOUSE_SECURE: boolean
    KAFKA_HOSTS: string
    KAFKA_CLIENT_CERT_B64: string | null
    KAFKA_CLIENT_CERT_KEY_B64: string | null
    KAFKA_TRUSTED_CERT_B64: string | null
    KAFKA_SECURITY_PROTOCOL: KafkaSecurityProtocol | null
    KAFKA_SASL_MECHANISM: KafkaSaslMechanism | null
    KAFKA_SASL_USER: string | null
    KAFKA_SASL_PASSWORD: string | null
    KAFKA_CONSUMPTION_TOPIC: string | null
    KAFKA_PRODUCER_MAX_QUEUE_SIZE: number
    KAFKA_MAX_MESSAGE_BATCH_SIZE: number
    KAFKA_FLUSH_FREQUENCY_MS: number
    REDIS_URL: string
    POSTHOG_REDIS_PASSWORD: string
    POSTHOG_REDIS_HOST: string
    POSTHOG_REDIS_PORT: number
    BASE_DIR: string
    PLUGINS_RELOAD_PUBSUB_CHANNEL: string
    LOG_LEVEL: LogLevel
    SENTRY_DSN: string | null
    STATSD_HOST: string | null
    STATSD_PORT: number
    STATSD_PREFIX: string
    SCHEDULE_LOCK_TTL: number
    REDIS_POOL_MIN_SIZE: number
    REDIS_POOL_MAX_SIZE: number
    DISABLE_MMDB: boolean
    DISTINCT_ID_LRU_SIZE: number
    EVENT_PROPERTY_LRU_SIZE: number
    INTERNAL_MMDB_SERVER_PORT: number
    JOB_QUEUES: string
    JOB_QUEUE_GRAPHILE_URL: string
    JOB_QUEUE_GRAPHILE_SCHEMA: string
    JOB_QUEUE_GRAPHILE_PREPARED_STATEMENTS: boolean
    JOB_QUEUE_S3_AWS_ACCESS_KEY: string
    JOB_QUEUE_S3_AWS_SECRET_ACCESS_KEY: string
    JOB_QUEUE_S3_AWS_REGION: string
    JOB_QUEUE_S3_BUCKET_NAME: string
    JOB_QUEUE_S3_PREFIX: string
    CRASH_IF_NO_PERSISTENT_JOB_QUEUE: boolean
    STALENESS_RESTART_SECONDS: number
    HEALTHCHECK_MAX_STALE_SECONDS: number
    CAPTURE_INTERNAL_METRICS: boolean
    PISCINA_USE_ATOMICS: boolean
    PISCINA_ATOMICS_TIMEOUT: number
    SITE_URL: string | null
    EXPERIMENTAL_EVENTS_LAST_SEEN_ENABLED: boolean
    EXPERIMENTAL_EVENT_PROPERTY_TRACKER_ENABLED: boolean
    MAX_PENDING_PROMISES_PER_WORKER: number
    KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY: number
    CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS: boolean
    CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS_TEAMS: string
    CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: string
    CONVERSION_BUFFER_ENABLED: boolean
    CONVERSION_BUFFER_ENABLED_TEAMS: string
    BUFFER_CONVERSION_SECONDS: number
    PERSON_INFO_TO_REDIS_TEAMS: string
    PERSON_INFO_CACHE_TTL: number
    KAFKA_HEALTHCHECK_SECONDS: number
    HISTORICAL_EXPORTS_ENABLED: boolean
    OBJECT_STORAGE_ENABLED: boolean
    OBJECT_STORAGE_ENDPOINT: string
    OBJECT_STORAGE_ACCESS_KEY_ID: string
    OBJECT_STORAGE_SECRET_ACCESS_KEY: string
    OBJECT_STORAGE_SESSION_RECORDING_FOLDER: string
    OBJECT_STORAGE_BUCKET: string
    PLUGIN_SERVER_MODE: 'ingestion' | 'async' | null
}

export interface Hub extends PluginsServerConfig {
    instanceId: UUID
    // what tasks this server will tackle - e.g. ingestion, scheduled plugins or others.
    capabilities: PluginServerCapabilities
    // active connections to Postgres, Redis, ClickHouse, Kafka, StatsD
    db: DB
    postgres: Pool
    redisPool: GenericPool<Redis>
    clickhouse: ClickHouse
    kafka: Kafka
    kafkaProducer: KafkaProducerWrapper
    objectStorage: ObjectStorage
    // metrics
    statsd?: StatsD
    internalMetrics?: InternalMetrics
    pluginMetricsJob: Job | undefined
    // currently enabled plugin status
    plugins: Map<PluginId, Plugin>
    pluginConfigs: Map<PluginConfigId, PluginConfig>
    pluginConfigsPerTeam: Map<TeamId, PluginConfig[]>
    pluginSchedule: Record<string, PluginConfigId[]> | null
    pluginSchedulePromises: Record<string, Record<PluginConfigId, Promise<any> | null>>
    // unique hash for each plugin config; used to verify IDs caught on stack traces for unhandled promise rejections
    pluginConfigSecrets: Map<PluginConfigId, string>
    pluginConfigSecretLookup: Map<string, PluginConfigId>
    // tools
    teamManager: TeamManager
    organizationManager: OrganizationManager
    pluginsApiKeyManager: PluginsApiKeyManager
    rootAccessManager: RootAccessManager
    promiseManager: PromiseManager
    actionManager: ActionManager
    actionMatcher: ActionMatcher
    hookCannon: HookCommander
    eventsProcessor: EventsProcessor
    jobQueueManager: JobQueueManager
    siteUrlManager: SiteUrlManager
    // diagnostics
    lastActivity: number
    lastActivityType: string
    statelessVms: StatelessVmMap
    conversionBufferEnabledTeams: Set<number>
}

export interface PluginServerCapabilities {
    ingestion?: boolean
    pluginScheduledTasks?: boolean
    processJobs?: boolean
    processAsyncHandlers?: boolean
    http?: boolean
}

export type OnJobCallback = (queue: EnqueuedJob[]) => Promise<void> | void
export interface EnqueuedJob {
    type: string
    payload: Record<string, any>
    timestamp: number
    pluginConfigId: number
    pluginConfigTeam: number
}

export interface JobQueue {
    startConsumer: (onJob: OnJobCallback) => Promise<void> | void
    stopConsumer: () => Promise<void> | void
    pauseConsumer: () => Promise<void> | void
    resumeConsumer: () => Promise<void> | void
    isConsumerPaused: () => boolean

    connectProducer: () => Promise<void> | void
    enqueue: (job: EnqueuedJob) => Promise<void> | void
    disconnectProducer: () => Promise<void> | void
}

export enum JobQueueType {
    FS = 'fs',
    Graphile = 'graphile',
}

export enum JobQueuePersistence {
    /** Job queues that store jobs on the local server */
    Local = 'local',
    /** Remote persistent job queues that can be read from concurrently */
    Concurrent = 'concurrent',
}

export type JobQueueExport = {
    type: JobQueueType
    persistence: JobQueuePersistence
    getQueue: (serverConfig: PluginsServerConfig) => JobQueue
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
export type PluginPublicJobPayload = Record<string, string>
export interface Plugin {
    id: number
    organization_id: string
    name: string
    plugin_type: 'local' | 'respository' | 'custom' | 'source'
    description?: string
    is_global: boolean
    is_preinstalled: boolean
    url?: string
    config_schema: Record<string, PluginConfigSchema> | PluginConfigSchema[]
    tag?: string
    archive: Buffer | null
    /** @deprecated Replaced with source__index_ts */
    source?: string
    /** Cached source for index.ts from a joined PluginSourceFile query */
    source__index_ts?: string
    /** Cached source for frontend.tsx from a joined PluginSourceFile query */
    source__frontend_tsx?: string
    error?: PluginError
    from_json?: boolean
    from_web?: boolean
    created_at: string
    updated_at: string
    capabilities?: PluginCapabilities
    metrics?: StoredPluginMetrics
    is_stateless?: boolean
    public_jobs?: Record<string, PluginPublicJobPayload>
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
    error?: PluginError
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
}

export type WorkerMethods = {
    runBufferEventPipeline: (event: PreIngestionEvent) => Promise<IngestEventResponse>
    runAsyncHandlersEventPipeline: (event: IngestionEvent) => Promise<void>
    runEventPipeline: (event: PluginEvent) => Promise<void>
}

export type VMMethods = {
    setupPlugin?: () => Promise<void>
    teardownPlugin?: () => Promise<void>
    onEvent?: (event: ProcessedPluginEvent) => Promise<void>
    onAction?: (action: Action, event: ProcessedPluginEvent) => Promise<void>
    onSnapshot?: (event: ProcessedPluginEvent) => Promise<void>
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
}

/** Usable event message. */
export interface EventMessage extends BaseEventMessage {
    data: PluginEvent
    now: DateTime
    sent_at: DateTime | null
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
    app_urls: string[]
    completed_snippet_onboarding: boolean
    opt_out_capture: boolean
    slack_incoming_webhook: string
    session_recording_opt_in: boolean
    ingested_event: boolean
}

/** Usable Element model. */
export interface Element {
    text?: string
    tag_name?: string
    href?: string
    attr_id?: string
    attr_class?: string[]
    nth_child?: number
    nth_of_type?: number
    attributes?: Record<string, any>
    event_id?: number
    order?: number
    group_id?: number
}

export interface ElementGroup {
    id: number
    hash: string
    team_id: number
}

/** Usable Event model. */
export interface Event {
    id: number
    event?: string
    properties: Record<string, any>
    elements?: Element[]
    timestamp: string
    team_id: number
    distinct_id: string
    elements_hash: string
    created_at: string
    person_properties: Record<string, any>
    group0_properties: Record<string, any>
    group1_properties: Record<string, any>
    group2_properties: Record<string, any>
    group3_properties: Record<string, any>
    group4_properties: Record<string, any>
}

export interface ClickHouseEvent extends Omit<Event, 'id' | 'elements' | 'elements_hash'> {
    uuid: string
    elements_chain: string
}

// Clickhouse event as read from kafka
export interface ClickhouseEventKafka {
    event: string
    timestamp: string
    team_id: number
    distinct_id: string
    created_at: string
    uuid: string
    elements_chain: string
    properties: string
    person_properties: string | null
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

/** Clickhouse Group model */
export interface ClickhouseGroup {
    group_type_index: GroupTypeIndex
    group_key: string
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

/** ClickHouse PersonDistinctId model. (person_distinct_id table) */
export interface ClickHousePersonDistinctId {
    team_id: number
    person_id: string
    distinct_id: string
    is_deleted: 0 | 1
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
    version: number
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
export enum ActionStepUrlMatching {
    Contains = 'contains',
    Regex = 'regex',
    Exact = 'exact',
}

export interface ActionStep {
    id: number
    action_id: number
    tag_name: string | null
    text: string | null
    href: string | null
    selector: string | null
    url: string | null
    url_matching: ActionStepUrlMatching | null
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
}

/** Usable Action model. */
export interface Action extends RawAction {
    steps: ActionStep[]
}

/** Action<>Event mapping row. */
export interface ActionEventPair {
    id: number
    action_id: Action['id']
    event_id: Event['id']
}

export interface SessionRecordingEvent {
    uuid: string
    timestamp: string
    team_id: number
    distinct_id: string
    session_id: string
    window_id: string
    snapshot_data: string
    created_at: string
}

export interface PostgresSessionRecordingEvent extends Omit<SessionRecordingEvent, 'uuid'> {
    id: string
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

export interface JobQueueConsumerControl {
    stop: () => Promise<void>
    resume: () => Promise<void> | void
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

export interface PropertyDefinitionType {
    id: string
    name: string
    is_numerical: boolean
    volume_30_day: number | null
    query_usage_30_day: number | null
    team_id: number
    property_type?: PropertyType
}

export interface EventPropertyType {
    id: string
    event: string
    property: string
    team_id: number
}

export type PluginFunction = 'onEvent' | 'onAction' | 'processEvent' | 'onSnapshot' | 'pluginTask'

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

export interface PreIngestionEvent {
    eventUuid: string
    event: string
    ip: string | null
    teamId: TeamId
    distinctId: string
    properties: Properties
    timestamp: DateTime | string
    elementsList: Element[]
}

export type IngestionEvent = PreIngestionEvent
