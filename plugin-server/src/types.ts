import ClickHouse from '@posthog/clickhouse'
import { Meta, PluginAttachment, PluginConfigSchema, PluginEvent, Properties } from '@posthog/plugin-scaffold'
import { Pool as GenericPool } from 'generic-pool'
import { StatsD } from 'hot-shots'
import { Redis } from 'ioredis'
import { Kafka } from 'kafkajs'
import { DateTime } from 'luxon'
import { JobQueueManager } from 'main/job-queues/job-queue-manager'
import { Job } from 'node-schedule'
import { Pool } from 'pg'
import { VM } from 'vm2'

import { DB } from './utils/db/db'
import { KafkaProducerWrapper } from './utils/db/kafka-producer-wrapper'
import { InternalMetrics } from './utils/internal-metrics'
import { PluginMetricsManager } from './utils/plugin-metrics'
import { UUID } from './utils/utils'
import { ActionManager } from './worker/ingestion/action-manager'
import { ActionMatcher } from './worker/ingestion/action-matcher'
import { HookCommander } from './worker/ingestion/hooks'
import { OrganizationManager } from './worker/ingestion/organization-manager'
import { EventsProcessor } from './worker/ingestion/process-event'
import { TeamManager } from './worker/ingestion/team-manager'
import { PluginsApiKeyManager } from './worker/vm/extensions/helpers/api-key-manager'
import { LazyPluginVM } from './worker/vm/lazy'

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

export interface PluginsServerConfig extends Record<string, any> {
    WORKER_CONCURRENCY: number
    TASKS_PER_WORKER: number
    TASK_TIMEOUT: number
    CELERY_DEFAULT_QUEUE: string
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
    KAFKA_ENABLED: boolean
    KAFKA_HOSTS: string | null
    KAFKA_CLIENT_CERT_B64: string | null
    KAFKA_CLIENT_CERT_KEY_B64: string | null
    KAFKA_TRUSTED_CERT_B64: string | null
    KAFKA_CONSUMPTION_TOPIC: string | null
    KAFKA_PRODUCER_MAX_QUEUE_SIZE: number
    KAFKA_MAX_MESSAGE_BATCH_SIZE: number
    KAFKA_FLUSH_FREQUENCY_MS: number
    PLUGINS_CELERY_QUEUE: string
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
    INTERNAL_MMDB_SERVER_PORT: number
    PLUGIN_SERVER_IDLE: boolean
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
    CAPTURE_INTERNAL_METRICS: boolean
    PISCINA_USE_ATOMICS: boolean
    PISCINA_ATOMICS_TIMEOUT: number
}

export interface Hub extends PluginsServerConfig {
    instanceId: UUID
    // active connections to Postgres, Redis, ClickHouse, Kafka, StatsD
    db: DB
    postgres: Pool
    redisPool: GenericPool<Redis>
    clickhouse?: ClickHouse
    kafka?: Kafka
    kafkaProducer?: KafkaProducerWrapper
    // metrics
    statsd?: StatsD
    internalMetrics?: InternalMetrics
    pluginMetricsManager: PluginMetricsManager
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
    actionManager: ActionManager
    actionMatcher: ActionMatcher
    hookCannon: HookCommander
    eventsProcessor: EventsProcessor
    jobQueueManager: JobQueueManager
    // diagnostics
    lastActivity: number
    lastActivityType: string
}

export interface Pausable {
    pause: () => Promise<void> | void
    resume: () => Promise<void> | void
    isPaused: () => boolean
}

export interface Queue extends Pausable {
    start: () => Promise<void> | void
    stop: () => Promise<void> | void
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
    S3 = 's3',
}

export enum JobQueuePersistence {
    /** Job queues that store jobs on the local server */
    Local = 'local',
    /** Remote persistent job queues that can be read from concurrently */
    Concurrent = 'concurrent',
    /** Remote persistent job queues that must be read from one redlocked server at a time */
    Redlocked = 'redlocked',
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
    source?: string
    error?: PluginError
    from_json?: boolean
    from_web?: boolean
    created_at: string
    updated_at: string
    capabilities?: PluginCapabilities
    metrics?: StoredPluginMetrics
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
    updated_at: string
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
    event?: PluginEvent | null
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
    onEvent: (event: PluginEvent) => Promise<void>
    onSnapshot: (event: PluginEvent) => Promise<void>
    processEvent: (event: PluginEvent) => Promise<PluginEvent | null>
    ingestEvent: (event: PluginEvent) => Promise<IngestEventResponse>
}

export type VMMethods = {
    setupPlugin?: () => Promise<void>
    teardownPlugin?: () => Promise<void>
    onEvent?: (event: PluginEvent) => Promise<void>
    onSnapshot?: (event: PluginEvent) => Promise<void>
    exportEvents?: (events: PluginEvent[]) => Promise<void>
    processEvent?: (event: PluginEvent) => Promise<PluginEvent>
}

export interface PluginConfigVMResponse {
    vm: VM
    methods: VMMethods
    tasks: Record<PluginTaskType, Record<string, PluginTask>>
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
}

export interface ClickHouseEvent extends Omit<Event, 'id' | 'elements' | 'elements_hash'> {
    uuid: string
    elements_chain: string
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
    _timestamp: string
    _offset: number
}

/** Properties shared by RawPerson and Person. */
export interface BasePerson {
    id: number
    team_id: number
    properties: Properties
    is_user_id: number
    is_identified: boolean
    uuid: string
    properties_last_updated_at: Record<string, any>
    properties_last_operation: Record<string, any> | null
}

/** Raw Person row from database. */
export interface RawPerson extends BasePerson {
    created_at: string
}

/** Usable Person model. */
export interface Person extends BasePerson {
    created_at: DateTime
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

/** Clickhouse Group model */
export interface ClickhouseGroup {
    group_type_index: number
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
}

/** ClickHouse PersonDistinctId model. */
export interface ClickHousePersonDistinctId {
    team_id: number
    person_id: string
    distinct_id: string
    is_deleted: 0 | 1
}

/** Usable Cohort model. */
export interface Cohort {
    id: number
    name: string
    deleted: boolean
    groups: any[]
    team_id: Team['id']
    created_at: string
    created_by_id: number
    is_calculating: boolean
    last_calculation: string
    errors_calculating: number
    is_static: boolean
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

export interface ScheduleControl {
    stopSchedule: () => Promise<void>
    reloadSchedule: () => Promise<void>
}

export interface JobQueueConsumerControl {
    stop: () => Promise<void>
    resume: () => Promise<void> | void
}

export type IngestEventResponse = { success?: boolean; error?: string }

export interface EventDefinitionType {
    id: string
    name: string
    volume_30_day: number | null
    query_usage_30_day: number | null
    team_id: number
}

export interface PropertyDefinitionType {
    id: string
    name: string
    is_numerical: boolean
    volume_30_day: number | null
    query_usage_30_day: number | null
    team_id: number
}

export type PluginFunction = 'onEvent' | 'processEvent' | 'onSnapshot' | 'pluginTask'

export enum CeleryTriggeredJobOperation {
    Start = 'start',
}

export type GroupTypeToColumnIndex = Record<string, number>
