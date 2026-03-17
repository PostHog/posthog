import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { Element, PluginEvent, Properties } from '~/plugin-scaffold'

import type { CdpConfig } from './cdp/config'
import { IntegrationManagerService } from './cdp/services/managers/integration-manager.service'
import { EncryptedFields } from './cdp/utils/encryption-utils'
import type { CommonConfig } from './common/config'
import { InternalCaptureService } from './common/services/internal-capture'
import { InternalFetchService } from './common/services/internal-fetch'
import type { IngestionConsumerConfig } from './ingestion/config'
import type { CookielessManager } from './ingestion/cookieless/cookieless-manager'
import { KafkaProducerWrapper } from './kafka/producer'
import type { LogsIngestionConsumerConfig } from './logs-ingestion/config'
import type { SessionRecordingApiConfig, SessionRecordingConfig } from './session-recording/config'
import { PostgresRouter } from './utils/db/postgres'
import { GeoIPService } from './utils/geoip'
import { PubSub } from './utils/pubsub'
import { TeamManager } from './utils/team-manager'
import { GroupTypeManager } from './worker/ingestion/group-type-manager'
import { ClickhouseGroupRepository } from './worker/ingestion/groups/repositories/clickhouse-group-repository'
import { GroupRepository } from './worker/ingestion/groups/repositories/group-repository.interface'
import { PersonRepository } from './worker/ingestion/persons/repositories/person-repository'

export { Element } from '~/plugin-scaffold' // Re-export Element from scaffolding, for backwards compat.

type Brand<K, T> = K & { __brand: T }

// Re-export config types from domain-specific files, this is to avoid mass refactors, we can eventually update it
export { CdpConfig } from './cdp/config'
export {
    CommonConfig,
    KafkaSaslMechanism,
    KafkaSecurityProtocol,
    LogLevel,
    PluginServerMode,
    stringToPluginServerMode,
} from './common/config'
export {
    IngestionConsumerConfig,
    IngestionLane,
    PersonBatchWritingDbWriteMode,
    PersonBatchWritingMode,
} from './ingestion/config'
export { LogsIngestionConsumerConfig } from './logs-ingestion/config'
export { SessionRecordingApiConfig, SessionRecordingConfig } from './session-recording/config'

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

export interface PluginsServerConfig
    extends CommonConfig,
        CdpConfig,
        IngestionConsumerConfig,
        LogsIngestionConsumerConfig,
        SessionRecordingConfig,
        SessionRecordingApiConfig {}

export interface HubServices {
    postgres: PostgresRouter
    redisPool: GenericPool<Redis>
    posthogRedisPool: GenericPool<Redis>
    cookielessRedisPool: GenericPool<Redis>
    kafkaProducer: KafkaProducerWrapper
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    groupRepository: GroupRepository
    clickhouseGroupRepository: ClickhouseGroupRepository
    personRepository: PersonRepository
    geoipService: GeoIPService
    encryptedFields: EncryptedFields
    cookielessManager: CookielessManager
    pubSub: PubSub
    integrationManager: IntegrationManagerService
    quotaLimiting: QuotaLimiting
    internalCaptureService: InternalCaptureService
    internalFetchService: InternalFetchService
}

export interface Hub extends PluginsServerConfig, HubServices {}

export interface PluginServerCapabilities {
    // Warning: when adding more entries, make sure to update worker/vm/capabilities.ts
    // and the shouldSetupPluginInServer() test accordingly.
    ingestionV2Combined?: boolean
    ingestionV2?: boolean
    logsIngestion?: boolean
    sessionRecordingBlobIngestionV2?: boolean
    sessionRecordingBlobIngestionV2Overflow?: boolean
    cdpProcessedEvents?: boolean
    cdpDataWarehouseEvents?: boolean
    cdpPersonUpdates?: boolean
    cdpInternalEvents?: boolean
    cdpLegacyOnEvent?: boolean
    cdpBatchHogFlow?: boolean
    cdpCyclotronWorker?: boolean
    cdpCyclotronWorkerHogFlow?: boolean
    cdpPrecalculatedFilters?: boolean
    cdpCohortMembership?: boolean
    cdpApi?: boolean
    appManagementSingleton?: boolean
    evaluationScheduler?: boolean
    cdpCyclotronV2Janitor?: boolean
    recordingApi?: boolean
    ingestionV2Testing?: boolean
}

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

export enum CookielessServerHashMode {
    Disabled = 0,
    Stateless = 1,
    Stateful = 2,
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
    default_anonymize_ips: boolean
}

// NOTE: We don't need to list all options here - only the ones we use
export type OrganizationAvailableFeature = 'group_analytics' | 'data_pipelines' | 'zapier'

/** Event schema with enforcement enabled. Only includes required properties since optional properties are not validated. */
export interface EventSchemaEnforcement {
    event_name: string
    /** Map from property name to accepted types (multiple types when property groups disagree) */
    required_properties: Map<string, string[]>
}

/** Usable Team model. */
export interface LogsSettings {
    capture_console_logs?: boolean
    json_parse_logs?: boolean
    retention_days?: number
    retention_last_updated?: string
}

export interface Team {
    id: number
    project_id: ProjectId
    uuid: string
    organization_id: string
    name: string
    anonymize_ips: boolean
    api_token: string
    secret_api_token: string | null
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
    logs_settings?: LogsSettings | null
    extra_settings: Record<string, string | number | boolean> | null
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
    team_id: TeamId
    distinct_id: string
    /** Person UUID. */
    person_id?: string
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
    captured_at?: ClickHouseTimestamp | null
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
    historical_migration?: boolean
}

export interface RawKafkaEvent extends RawClickHouseEvent {
    /**
     * The project ID field is only included in the `clickhouse_events_json` topic, not present in ClickHouse.
     * That's because we need it in `property-defs-rs` and not elsewhere.
     */
    project_id: ProjectId
}

/** Pre-serialization event produced by create-event, before ClickHouse formatting. */
export interface ProcessedEvent {
    uuid: string
    event: string
    properties: Record<string, unknown>
    timestamp: ISOTimestamp
    team_id: TeamId
    project_id: ProjectId
    distinct_id: string
    elements_chain: string
    created_at: null
    captured_at: Date | null
    person_id: string
    person_properties: Record<string, unknown>
    person_created_at: DateTime | null
    person_mode: PersonMode
    historical_migration?: boolean
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
    last_seen_at: string | null
}

/** Usable Person model. */
export interface InternalPerson extends BasePerson {
    created_at: DateTime
    version: number
    last_seen_at: DateTime | null
}

/** Mutable fields that can be updated on a Person via updatePerson. */
export interface PersonUpdateFields {
    properties: Properties
    properties_last_updated_at: PropertiesLastUpdatedAt
    properties_last_operation: PropertiesLastOperation | null
    is_identified: boolean
    created_at: DateTime
    version?: number // Optional: allows forcing a specific version
    last_seen_at?: DateTime | null
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
    last_seen_at: string | null
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
}

export interface EventHeaders {
    token?: string
    distinct_id?: string
    session_id?: string
    timestamp?: string
    event?: string
    uuid?: string
    now?: Date
    force_disable_person_processing: boolean
    historical_migration: boolean
}

export interface IncomingEvent {
    event: PipelineEvent
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
