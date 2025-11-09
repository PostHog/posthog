import { LogicWrapper } from 'kea'
import type { PostHog, PropertyMatchType, SupportedWebVitalsMetrics } from 'posthog-js'
import { ReactNode } from 'react'
import { Layout } from 'react-grid-layout'

import { LemonTableColumns } from '@posthog/lemon-ui'
import { PluginConfigSchema } from '@posthog/plugin-scaffold'
import { LogLevel } from '@posthog/rrweb-plugin-console-record'
import { eventWithTime } from '@posthog/rrweb-types'

import { ChartDataset, ChartType, InteractionItem } from 'lib/Chart'
import { PaginatedResponse } from 'lib/api'
import { AlertType } from 'lib/components/Alerts/types'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { DashboardCompatibleScenes } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { CommonFilters, HeatmapFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'
import {
    BIN_COUNT_AUTO,
    ENTITY_MATCH_TYPE,
    FunnelLayout,
    OrganizationMembershipLevel,
    PROPERTY_MATCH_TYPE,
    PluginsAccessLevel,
    RETENTION_FIRST_EVER_OCCURRENCE,
    RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
    RETENTION_MEAN_NONE,
    RETENTION_RECURRING,
    ShownAsValue,
    TeamMembershipLevel,
} from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { PopoverProps } from 'lib/lemon-ui/Popover/Popover'
import { BehavioralFilterKey, BehavioralFilterType } from 'scenes/cohorts/CohortFilters/types'
import { BreakdownColorConfig } from 'scenes/dashboard/DashboardInsightColorsModal'
import {
    ConversionRateInputType,
    EventConfig,
} from 'scenes/experiments/RunningTimeCalculator/runningTimeCalculatorLogic'
import { AggregationAxisFormat } from 'scenes/insights/aggregationAxisFormat'
import { Params, Scene, SceneConfig } from 'scenes/sceneTypes'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SurveyRatingScaleValue, WEB_SAFE_FONTS } from 'scenes/surveys/constants'

import { RootAssistantMessage } from '~/queries/schema/schema-assistant-messages'
import type {
    CurrencyCode,
    DashboardFilter,
    DataWarehouseManagedViewsetKind,
    DatabaseSchemaField,
    ExperimentExposureCriteria,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    ExternalDataSourceType,
    FileSystemIconType,
    FileSystemImport,
    HogQLQuery,
    HogQLQueryModifiers,
    HogQLVariable,
    InsightQueryNode,
    InsightVizNode,
    MarketingAnalyticsConfig,
    Node,
    NodeKind,
    QuerySchema,
    QueryStatus,
    RecordingOrder,
    RecordingsQuery,
    RevenueAnalyticsConfig,
    SharingConfigurationSettings,
    TileFilters,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { CyclotronInputType } from 'products/workflows/frontend/Workflows/hogflows/steps/types'
import { HogFlow } from 'products/workflows/frontend/Workflows/hogflows/types'

// Type alias for number to be reflected as integer in json-schema.
/** @asType integer */
type integer = number

export type Optional<T, K extends string | number | symbol> = Omit<T, K> & { [K in keyof T]?: T[K] }

/** Make all keys of T required except those in K */
export type RequiredExcept<T, K extends keyof T> = {
    [P in Exclude<keyof T, K>]-?: T[P]
} & {
    [P in K]?: T[P]
}

// Keep this in sync with backend constants/features/{product_name}.yml

export enum AvailableFeature {
    APPS = 'apps',
    SLACK_INTEGRATION = 'slack_integration',
    MICROSOFT_TEAMS_INTEGRATION = 'microsoft_teams_integration',
    DISCORD_INTEGRATION = 'discord_integration',
    ZAPIER = 'zapier',
    APP_METRICS = 'app_metrics',
    DATA_PIPELINES = 'data_pipelines',
    RECORDINGS_PLAYLISTS = 'recordings_playlists',
    SESSION_REPLAY_DATA_RETENTION = 'session_replay_data_retention',
    CONSOLE_LOGS = 'console_logs',
    RECORDINGS_PERFORMANCE = 'recordings_performance',
    SESSION_REPLAY_NETWORK_PAYLOADS = 'session_replay_network_payloads',
    RECORDINGS_FILE_EXPORT = 'recordings_file_export',
    SESSION_REPLAY_SAMPLING = 'session_replay_sampling',
    REPLAY_RECORDING_DURATION_MINIMUM = 'replay_recording_duration_minimum',
    REPLAY_FEATURE_FLAG_BASED_RECORDING = 'replay_feature_flag_based_recording',
    REPLAY_MASK_SENSITIVE_DATA = 'replay_mask_sensitive_data',
    REPLAY_SHARING_EMBEDDING = 'replay_sharing_embedding',
    REPLAY_PRODUCT_ANALYTICS_INTEGRATION = 'replay_product_analytics_integration',
    REPLAY_FILTER_PERSON_PROPERTIES = 'replay_filter_person_properties',
    REPLAY_FILTER_EVENTS = 'replay_filter_events',
    REPLAY_DOM_EXPLORER = 'replay_dom_explorer',
    WORKS_WITH_POSTHOG_JS = 'works_with_posthog_js',
    REPLAY_AUTOMATIC_PLAYLISTS = 'replay_automatic_playlists',
    MOBILE_REPLAY = 'mobile_replay',
    GROUP_ANALYTICS = 'group_analytics',
    SURVEYS_UNLIMITED_SURVEYS = 'surveys_unlimited_surveys',
    SURVEYS_ALL_QUESTION_TYPES = 'surveys_all_question_types',
    SURVEYS_MULTIPLE_QUESTIONS = 'surveys_multiple_questions',
    SURVEYS_USER_TARGETING = 'surveys_user_targeting',
    SURVEYS_USER_SAMPLING = 'surveys_user_sampling',
    SURVEYS_STYLING = 'surveys_styling',
    SURVEYS_TEXT_HTML = 'surveys_text_html',
    SURVEYS_API_MODE = 'surveys_api_mode',
    SURVEYS_RESULTS_ANALYSIS = 'surveys_results_analysis',
    SURVEYS_TEMPLATES = 'surveys_templates',
    SURVEYS_DATA_RETENTION = 'surveys_data_retention',
    SURVEYS_LINK_QUESTION_TYPE = 'surveys_link_question_type',
    SURVEYS_SLACK_NOTIFICATIONS = 'surveys_slack_notifications',
    SURVEYS_WAIT_PERIODS = 'surveys_wait_periods',
    SURVEYS_RECURRING = 'surveys_recurring',
    SURVEYS_EVENTS = 'surveys_events',
    SURVEYS_ACTIONS = 'surveys_actions',
    TRACKED_USERS = 'tracked_users',
    TEAM_MEMBERS = 'team_members',
    API_ACCESS = 'api_access',
    ORGANIZATIONS_PROJECTS = 'organizations_projects',
    ENVIRONMENTS = 'environments',
    ROLE_BASED_ACCESS = 'role_based_access',
    SOCIAL_SSO = 'social_sso',
    SAML = 'saml',
    SCIM = 'scim',
    SSO_ENFORCEMENT = 'sso_enforcement',
    WHITE_LABELLING = 'white_labelling',
    COMMUNITY_SUPPORT = 'community_support',
    DEDICATED_SUPPORT = 'dedicated_support',
    EMAIL_SUPPORT = 'email_support',
    ACCOUNT_MANAGER = 'account_manager',
    TRAINING = 'training',
    CONFIGURATION_SUPPORT = 'configuration_support',
    TERMS_AND_CONDITIONS = 'terms_and_conditions',
    SECURITY_ASSESSMENT = 'security_assessment',
    BESPOKE_PRICING = 'bespoke_pricing',
    INVOICE_PAYMENTS = 'invoice_payments',
    BOOLEAN_FLAGS = 'boolean_flags',
    FEATURE_FLAGS_DATA_RETENTION = 'feature_flags_data_retention',
    MULTIVARIATE_FLAGS = 'multivariate_flags',
    PERSIST_FLAGS_CROSS_AUTHENTICATION = 'persist_flags_cross_authentication',
    FEATURE_FLAG_PAYLOADS = 'feature_flag_payloads',
    MULTIPLE_RELEASE_CONDITIONS = 'multiple_release_conditions',
    RELEASE_CONDITION_OVERRIDES = 'release_condition_overrides',
    TARGETING_BY_GROUP = 'targeting_by_group',
    LOCAL_EVALUATION_AND_BOOTSTRAPPING = 'local_evaluation_and_bootstrapping',
    FLAG_USAGE_STATS = 'flag_usage_stats',
    USER_OPT_IN = 'user_opt_in',
    INSTANT_ROLLBACKS = 'instant_rollbacks',
    EXPERIMENTATION = 'experimentation',
    GROUP_EXPERIMENTS = 'group_experiments',
    FUNNEL_EXPERIMENTS = 'funnel_experiments',
    SECONDARY_METRICS = 'secondary_metrics',
    STATISTICAL_ANALYSIS = 'statistical_analysis',
    PRODUCT_ANALYTICS_DATA_RETENTION = 'product_analytics_data_retention',
    DASHBOARDS = 'dashboards',
    FUNNELS = 'funnels',
    GRAPHS_TRENDS = 'graphs_trends',
    PATHS = 'paths',
    INSIGHTS = 'insights',
    SUBSCRIPTIONS = 'subscriptions',
    ADVANCED_PERMISSIONS = 'advanced_permissions', // TODO: Remove this once access_control is propagated
    ACCESS_CONTROL = 'access_control',
    INGESTION_TAXONOMY = 'ingestion_taxonomy',
    PATHS_ADVANCED = 'paths_advanced',
    CORRELATION_ANALYSIS = 'correlation_analysis',
    TAGGING = 'tagging',
    BEHAVIORAL_COHORT_FILTERING = 'behavioral_cohort_filtering',
    PRODUCT_ANALYTICS_RETENTION = 'product_analytics_retention',
    PRODUCT_ANALYTICS_STICKINESS = 'product_analytics_stickiness',
    AUTOCAPTURE = 'autocapture',
    DATA_VISUALIZATION = 'data_visualization',
    PRODUCT_ANALYTICS_SQL_QUERIES = 'product_analytics_sql_queries',
    TWOFA_ENFORCEMENT = '2fa_enforcement',
    AUDIT_LOGS = 'audit_logs',
    HIPAA_BAA = 'hipaa_baa',
    CUSTOM_MSA = 'custom_msa',
    TWOFA = '2fa',
    PRIORITY_SUPPORT = 'priority_support',
    SUPPORT_RESPONSE_TIME = 'support_response_time',
    AUTOMATIC_PROVISIONING = 'automatic_provisioning',
    MANAGED_REVERSE_PROXY = 'managed_reverse_proxy',
    ALERTS = 'alerts',
    DATA_COLOR_THEMES = 'data_color_themes',
    ORGANIZATION_INVITE_SETTINGS = 'organization_invite_settings',
    ORGANIZATION_SECURITY_SETTINGS = 'organization_security_settings',
}

type AvailableFeatureUnion = `${AvailableFeature}`

export enum ProductKey {
    COHORTS = 'cohorts',
    ACTIONS = 'actions',
    ALERTS = 'alerts',
    EXPERIMENTS = 'experiments',
    FEATURE_FLAGS = 'feature_flags',
    ANNOTATIONS = 'annotations',
    COMMENTS = 'comments',
    HISTORY = 'history',
    HEATMAPS = 'heatmaps',
    INGESTION_WARNINGS = 'ingestion_warnings',
    PERSONS = 'persons',
    SURVEYS = 'surveys',
    SESSION_REPLAY = 'session_replay',
    MOBILE_REPLAY = 'mobile_replay',
    DATA_WAREHOUSE = 'data_warehouse',
    DATA_WAREHOUSE_SAVED_QUERY = 'data_warehouse_saved_queries',
    EARLY_ACCESS_FEATURES = 'early_access_features',
    USER_INTERVIEWS = 'user_interviews',
    PRODUCT_ANALYTICS = 'product_analytics',
    PIPELINE_TRANSFORMATIONS = 'pipeline_transformations',
    PIPELINE_DESTINATIONS = 'pipeline_destinations',
    SITE_APPS = 'site_apps',
    GROUP_ANALYTICS = 'group_analytics',
    INTEGRATIONS = 'integrations',
    PLATFORM_AND_SUPPORT = 'platform_and_support',
    TEAMS = 'teams',
    WEB_ANALYTICS = 'web_analytics',
    ERROR_TRACKING = 'error_tracking',
    REVENUE_ANALYTICS = 'revenue_analytics',
    MARKETING_ANALYTICS = 'marketing_analytics',
    LLM_ANALYTICS = 'llm_analytics',
    MAX = 'max',
    LINKS = 'links',
    ENDPOINTS = 'endpoints',
}

type ProductKeyUnion = `${ProductKey}`

export enum LicensePlan {
    Scale = 'scale',
    Enterprise = 'enterprise',
    Dev = 'dev',
    Cloud = 'cloud',
}

export enum BillingPlan {
    Free = 'free',
    Paid = 'paid',
    Teams = 'teams', // Legacy
    Boost = 'boost',
    Scale = 'scale',
    Enterprise = 'enterprise',
}

export enum StartupProgramLabel {
    YC = 'YC',
    Startup = 'Startup',
}

export enum Realm {
    Cloud = 'cloud',
    Demo = 'demo',
    SelfHostedPostgres = 'hosted',
    SelfHostedClickHouse = 'hosted-clickhouse',
}

export enum Region {
    US = 'US',
    EU = 'EU',
}

export type SSOProvider = 'google-oauth2' | 'github' | 'gitlab' | 'saml'

export interface AuthBackends {
    'google-oauth2'?: boolean
    gitlab?: boolean
    github?: boolean
}

export type ColumnChoice = string[] | 'DEFAULT'

export interface ColumnConfig {
    active: ColumnChoice
}

export type WithAccessControl = {
    user_access_level: AccessControlLevel
}

export enum AccessControlResourceType {
    Project = 'project',
    Organization = 'organization',
    Action = 'action',
    FeatureFlag = 'feature_flag',
    Insight = 'insight',
    Dashboard = 'dashboard',
    Notebook = 'notebook',
    SessionRecording = 'session_recording',
    RevenueAnalytics = 'revenue_analytics',
    Survey = 'survey',
    Experiment = 'experiment',
    WebAnalytics = 'web_analytics',
}

interface UserBaseType {
    uuid: string
    distinct_id: string
    first_name: string
    last_name?: string
    email: string
}

/* Type for User objects in nested serializers (e.g. created_by) */
export interface UserBasicType extends UserBaseType {
    is_email_verified?: any
    id: number
    hedgehog_config?: MinimalHedgehogConfig
    role_at_organization?: string | null
}

/**
 * A user can have scene dashboard choices for multiple teams
 * TODO does this only have the current team's choices?
 */
export interface SceneDashboardChoice {
    scene: DashboardCompatibleScenes
    dashboard: number | DashboardBasicType
}

export type UserTheme = 'light' | 'dark' | 'system'

/** Full User model. */
export interface UserType extends UserBaseType {
    date_joined: string
    notification_settings: {
        plugin_disabled: boolean
        project_weekly_digest_disabled: Record<number, boolean>
        all_weekly_digest_disabled: boolean
        error_tracking_issue_assigned: boolean
        discussions_mentioned: boolean
    }
    events_column_config: ColumnConfig
    anonymize_data: boolean
    toolbar_mode: 'disabled' | 'toolbar'
    has_password: boolean
    id: number
    is_staff: boolean
    is_impersonated: boolean
    is_impersonated_until?: string
    sensitive_session_expires_at: string
    organization: OrganizationType | null
    team: TeamBasicType | null
    organizations: OrganizationBasicType[]
    realm?: Realm
    is_email_verified?: boolean | null
    pending_email?: string | null
    is_2fa_enabled: boolean
    has_social_auth: boolean
    has_sso_enforcement: boolean
    has_seen_product_intro_for?: Record<string, boolean>
    scene_personalisation?: SceneDashboardChoice[]
    theme_mode?: UserTheme | null
    hedgehog_config?: Partial<HedgehogConfig>
    role_at_organization?: string
}

export type HedgehogColorOptions =
    | 'green'
    | 'red'
    | 'blue'
    | 'purple'
    | 'dark'
    | 'light'
    | 'sepia'
    | 'invert'
    | 'invert-hue'
    | 'greyscale'

export interface MinimalHedgehogConfig {
    use_as_profile: boolean
    color: HedgehogColorOptions | null
    accessories: string[]
}

export type HedgehogSkin = 'default' | 'spiderhog' | 'robohog'

export interface HedgehogConfig extends MinimalHedgehogConfig {
    enabled: boolean
    color: HedgehogColorOptions | null
    skin?: HedgehogSkin
    accessories: string[]
    walking_enabled: boolean
    interactions_enabled: boolean
    controls_enabled: boolean
    party_mode_enabled: boolean
    fixed_direction?: 'left' | 'right'
}

export interface NotificationSettings {
    plugin_disabled: boolean
    project_weekly_digest_disabled: Record<string, boolean>
    all_weekly_digest_disabled: boolean
    error_tracking_issue_assigned: boolean
    discussions_mentioned: boolean
}

export interface PluginAccess {
    view: boolean
    install: boolean
    configure: boolean
}

export interface PersonalAPIKeyType {
    id: string
    label: string
    value?: string
    mask_value?: string | null
    created_at: string
    last_used_at: string | null
    last_rolled_at: string | null
    team_id: number
    user_id: string
    scopes: string[]
    scoped_organizations?: OrganizationType['id'][] | null
    scoped_teams?: TeamType['id'][] | null
}

export interface OrganizationBasicType {
    id: string
    name: string
    slug: string
    logo_media_id: string | null
    membership_level: OrganizationMembershipLevel | null
    members_can_use_personal_api_keys: boolean
    allow_publicly_shared_resources: boolean
}

interface OrganizationMetadata {
    instance_tag?: string
}

export interface OrganizationType extends OrganizationBasicType {
    created_at: string
    updated_at: string
    plugins_access_level: PluginsAccessLevel
    teams: TeamBasicType[]
    projects: ProjectBasicType[]
    available_product_features: BillingFeatureType[]
    is_member_join_email_enabled: boolean
    customer_id: string | null
    enforce_2fa: boolean | null
    is_ai_data_processing_approved?: boolean
    members_can_invite?: boolean
    members_can_use_personal_api_keys: boolean
    allow_publicly_shared_resources: boolean
    metadata?: OrganizationMetadata
    member_count: number
    default_experiment_stats_method: ExperimentStatsMethod
    default_anonymize_ips?: boolean
    default_role_id?: string | null
}

export interface OrganizationDomainType {
    id: string
    domain: string
    is_verified: boolean
    verified_at: string // Datetime
    verification_challenge: string
    jit_provisioning_enabled: boolean
    sso_enforcement: SSOProvider | ''
    has_saml: boolean
    saml_entity_id: string
    saml_acs_url: string
    saml_x509_cert: string
    scim_enabled?: boolean
    scim_base_url?: string
    scim_bearer_token?: string
}

/** Member properties relevant at both organization and project level. */
export interface BaseMemberType {
    id: string
    user: UserBasicType
    last_login: string | null
    joined_at: string
    updated_at: string
    is_2fa_enabled: boolean
    has_social_auth: boolean
}

export interface OrganizationMemberType extends BaseMemberType {
    /** Level at which the user is in the organization. */
    level: OrganizationMembershipLevel
    is_2fa_enabled: boolean
}

export interface OrganizationMemberScopedApiKeysResponse {
    has_keys: boolean
    has_keys_active_last_week: boolean
    keys: {
        name: string
        last_used_at: string | null
    }[]
}

/**
 * This interface is only used in the frontend for fusing organization member data.
 */
export interface FusedTeamMemberType extends BaseMemberType {
    /**
     * Level at which the user explicitly is in the project.
     * Null means that membership is implicit (when showing permitted members)
     * or that there's no membership at all (when showing addable members).
     */
    explicit_team_level: TeamMembershipLevel | null
    /** Level at which the user is in the organization. */
    organization_level: OrganizationMembershipLevel
    /** Effective level of the user within the project. */
    level: OrganizationMembershipLevel
}

export interface ListOrganizationMembersParams {
    offset?: number
    limit?: number
    updated_after?: string
}

export interface APIErrorType {
    type: 'authentication_error' | 'invalid_request' | 'server_error' | 'throttled_error' | 'validation_error'
    code: string
    detail: string
    attr: string | null
}

export interface EventUsageType {
    event: string
    usage_count: number
    volume: number
}

export interface PropertyUsageType {
    key: string
    usage_count: number
    volume: number
}

export interface ProjectBasicType {
    id: number
    organization_id: string
    name: string
}

export interface TeamBasicType extends WithAccessControl {
    id: number
    uuid: string
    organization: string // Organization ID
    project_id: number
    api_token: string
    secret_api_token: string
    secret_api_token_backup: string
    name: string
    completed_snippet_onboarding: boolean
    has_completed_onboarding_for?: Record<string, boolean>
    ingested_event: boolean
    is_demo: boolean
    timezone: string
}

export interface CorrelationConfigType {
    excluded_person_property_names?: string[]
    excluded_event_property_names?: string[]
    excluded_event_names?: string[]
}

export interface SessionRecordingAIConfig {
    opt_in: boolean
    preferred_events: string[]
    excluded_events: string[]
    included_event_properties: string[]
    important_user_properties: string[]
}

export interface ProjectType extends ProjectBasicType {
    created_at: string
}

export interface TeamSurveyConfigType {
    appearance?: SurveyAppearance
}

export type SessionRecordingMaskingLevel = 'normal' | 'total-privacy' | 'free-love'

export type SessionRecordingRetentionPeriod = 'legacy' | '30d' | '90d' | '1y' | '5y'

export interface SessionRecordingMaskingConfig {
    maskAllInputs?: boolean
    maskTextSelector?: string
    blockSelector?: string
}

export enum ActivationTaskStatus {
    COMPLETED = 'completed',
    SKIPPED = 'skipped',
}

export interface TeamType extends TeamBasicType {
    created_at: string
    updated_at: string
    anonymize_ips: boolean
    app_urls: string[]
    recording_domains: string[]
    slack_incoming_webhook: string
    autocapture_opt_out: boolean
    session_recording_opt_in: boolean
    // These fields in the database accept null values and were previously set to NULL by default
    capture_console_log_opt_in: boolean | null
    capture_performance_opt_in: boolean | null
    capture_dead_clicks: boolean | null
    // a string representation of the decimal value between 0 and 1
    session_recording_sample_rate: string
    session_recording_minimum_duration_milliseconds: number | null
    session_recording_linked_flag: ({ variant?: string | null } & Pick<FeatureFlagBasicType, 'id' | 'key'>) | null
    session_recording_network_payload_capture_config:
        | { recordHeaders?: boolean; recordBody?: boolean }
        | undefined
        | null
    session_recording_masking_config: SessionRecordingMaskingConfig | undefined | null
    session_recording_retention_period: SessionRecordingRetentionPeriod | null
    session_replay_config: { record_canvas?: boolean; ai_config?: SessionRecordingAIConfig } | undefined | null
    survey_config?: TeamSurveyConfigType
    autocapture_exceptions_opt_in: boolean
    autocapture_web_vitals_opt_in?: boolean
    autocapture_web_vitals_allowed_metrics?: SupportedWebVitalsMetrics[]
    session_recording_url_trigger_config?: SessionReplayUrlTriggerConfig[]
    session_recording_url_blocklist_config?: SessionReplayUrlTriggerConfig[]
    session_recording_event_trigger_config?: string[]
    session_recording_trigger_match_type_config?: 'all' | 'any' | null
    surveys_opt_in?: boolean
    heatmaps_opt_in?: boolean
    web_analytics_pre_aggregated_tables_enabled?: boolean
    web_analytics_pre_aggregated_tables_version?: 'v1' | 'v2'
    autocapture_exceptions_errors_to_ignore: string[]
    test_account_filters: AnyPropertyFilter[]
    test_account_filters_default_checked: boolean
    /** 0 or unset for Sunday, 1 for Monday. */
    week_start_day?: number
    path_cleaning_filters: PathCleaningFilter[]
    data_attributes: string[]
    person_display_name_properties: string[]
    has_group_types: boolean
    group_types: GroupType[]
    primary_dashboard: number | null // Dashboard shown on the project homepage
    live_events_columns: string[] | null // Custom columns shown on the Live Events page
    live_events_token: string
    cookieless_server_hash_mode?: CookielessServerHashMode
    human_friendly_comparison_periods: boolean
    revenue_analytics_config: RevenueAnalyticsConfig
    onboarding_tasks?: {
        [key: string]: ActivationTaskStatus
    }

    /** Effective access level of the user in this specific team. Null if user has no access. */
    effective_membership_level: OrganizationMembershipLevel | null

    /** Used to exclude person properties from correlation analysis results.
     *
     * For example can be used to exclude properties that have trivial causation.
     * This field should have a default value of `{}`, but it IS nullable and can be `null` in some cases.
     */
    correlation_config: CorrelationConfigType | null
    person_on_events_querying_enabled: boolean
    extra_settings?: Record<string, string | number | boolean | undefined>
    modifiers?: HogQLQueryModifiers
    default_modifiers?: HogQLQueryModifiers
    product_intents?: ProductIntentType[]
    default_data_theme?: number
    flags_persistence_default: boolean
    feature_flag_confirmation_enabled: boolean
    feature_flag_confirmation_message: string
    default_evaluation_environments_enabled: boolean
    marketing_analytics_config: MarketingAnalyticsConfig
    base_currency: CurrencyCode
    managed_viewsets: Record<DataWarehouseManagedViewsetKind, boolean>
    experiment_recalculation_time?: string | null
    receive_org_level_activity_logs: boolean | null
}

export interface ProductIntentType {
    product_type: string
    created_at: string
    onboarding_completed_at?: string
}

// This type would be more correct without `Partial<TeamType>`, but it's only used in the shared dashboard/insight
// scenes, so not worth the refactor to use the `isAuthenticatedTeam()` check
export type TeamPublicType = Partial<TeamType> & Pick<TeamType, 'id' | 'uuid' | 'name' | 'timezone'>

export interface ActionType extends WithAccessControl {
    count?: number
    created_at: string
    deleted?: boolean
    id: number
    is_calculating?: boolean
    last_calculated_at?: string
    last_updated_at?: string // alias for last_calculated_at to achieve event and action parity
    name: string | null
    description?: string
    post_to_slack?: boolean
    slack_message_format?: string
    steps?: ActionStepType[]
    created_by: UserBasicType | null
    tags?: string[]
    verified?: boolean
    is_action?: true
    action_id?: number // alias of id to make it compatible with event definitions uuid
    bytecode?: any[]
    bytecode_error?: string
    pinned_at: string | null
    _create_in_folder?: string | null
}

/** Sync with plugin-server/src/types.ts */
export type ActionStepStringMatching = 'contains' | 'exact' | 'regex'

export interface ActionStepType {
    event?: string | null
    properties?: AnyPropertyFilter[]
    selector?: string | null
    /** @deprecated Only `selector` should be used now. */
    tag_name?: string
    text?: string | null
    /** @default StringMatching.Exact */
    text_matching?: ActionStepStringMatching | null
    href?: string | null
    /** @default ActionStepStringMatching.Exact */
    href_matching?: ActionStepStringMatching | null
    url?: string | null
    /** @default StringMatching.Contains */
    url_matching?: ActionStepStringMatching | null
    name?: string | null
}

export interface ElementType {
    attr_class?: string[]
    attr_id?: string
    attributes: Record<string, string>
    href?: string
    nth_child?: number
    nth_of_type?: number
    order?: number
    tag_name: string
    text?: string
}

export type ToolbarUserIntent = 'add-action' | 'edit-action' | 'heatmaps' | 'add-experiment' | 'edit-experiment'
export type ToolbarSource = 'url' | 'localstorage'
export type ToolbarVersion = 'toolbar'

export type ExperimentIdType = number | 'new' | 'web'
/* sync with posthog-js */
export interface ToolbarParams {
    apiURL?: string
    token?: string /** public posthog-js token */
    temporaryToken?: string /** private temporary user token */
    actionId?: number
    experimentId?: ExperimentIdType
    userIntent?: ToolbarUserIntent
    source?: ToolbarSource
    toolbarVersion?: ToolbarVersion
    instrument?: boolean
    distinctId?: string
    userEmail?: string
    dataAttributes?: string[]
    featureFlags?: Record<string, string | boolean>
}

export interface ToolbarProps extends ToolbarParams {
    posthog?: PostHog
    disableExternalStyles?: boolean
}

export type PathCleaningFilter = { alias?: string; regex?: string; order?: number }

export type PropertyFilterBaseValue = string | number | bigint | boolean
export type PropertyFilterValue = PropertyFilterBaseValue | PropertyFilterBaseValue[] | null

/** Sync with plugin-server/src/types.ts */
export enum PropertyOperator {
    Exact = 'exact',
    IsNot = 'is_not',
    IContains = 'icontains',
    NotIContains = 'not_icontains',
    Regex = 'regex',
    NotRegex = 'not_regex',
    GreaterThan = 'gt',
    GreaterThanOrEqual = 'gte',
    LessThan = 'lt',
    LessThanOrEqual = 'lte',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
    IsDateExact = 'is_date_exact',
    IsDateBefore = 'is_date_before',
    IsDateAfter = 'is_date_after',
    Between = 'between',
    NotBetween = 'not_between',
    Minimum = 'min',
    Maximum = 'max',
    In = 'in',
    NotIn = 'not_in',
    IsCleanedPathExact = 'is_cleaned_path_exact',
    FlagEvaluatesTo = 'flag_evaluates_to',
}

export enum SavedInsightsTabs {
    All = 'all',
    Yours = 'yours',
    Favorites = 'favorites',
    History = 'history',
    Alerts = 'alerts',
}

export enum ReplayTabs {
    Home = 'home',
    Playlists = 'playlists',
    Templates = 'templates',
    Settings = 'settings',
}

export type ReplayTab = {
    label: string
    key: ReplayTabs
    tooltip?: string
    tooltipDocLink?: string
    'data-attr'?: string
}

export enum ExperimentsTabs {
    All = 'all',
    Yours = 'yours',
    Archived = 'archived',
    Holdouts = 'holdouts',
    SharedMetrics = 'shared-metrics',
    History = 'history',
    Settings = 'settings',
}

export enum ActivityTab {
    ExploreEvents = 'explore',
    LiveEvents = 'live',
}

export enum ProgressStatus {
    Draft = 'draft',
    Running = 'running',
    Complete = 'complete',
}

export enum PropertyFilterType {
    /** Event metadata and fields on the clickhouse events table */
    Meta = 'meta',
    /** Event properties */
    Event = 'event',
    InternalEvent = 'internal_event',
    EventMetadata = 'event_metadata',
    /** Person properties */
    Person = 'person',
    Element = 'element',
    /** Event property with "$feature/" prepended */
    Feature = 'feature',
    Session = 'session',
    Cohort = 'cohort',
    Recording = 'recording',
    LogEntry = 'log_entry',
    Group = 'group',
    HogQL = 'hogql',
    DataWarehouse = 'data_warehouse',
    DataWarehousePersonProperty = 'data_warehouse_person_property',
    ErrorTrackingIssue = 'error_tracking_issue',
    RevenueAnalytics = 'revenue_analytics',
    /** Feature flag dependency */
    Flag = 'flag',
    Log = 'log',
}

/** Sync with plugin-server/src/types.ts */
interface BasePropertyFilter {
    key: string
    value?: PropertyFilterValue
    label?: string
    type?: PropertyFilterType
}

/** Sync with plugin-server/src/types.ts */
export interface EventPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Event
    /** @default 'exact' */
    operator: PropertyOperator
}

export interface EventMetadataPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.EventMetadata
    operator: PropertyOperator
}

export interface RevenueAnalyticsPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.RevenueAnalytics
    operator: PropertyOperator
}

/** Sync with plugin-server/src/types.ts */
export interface PersonPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Person
    operator: PropertyOperator
}

export interface DataWarehousePropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.DataWarehouse
    operator: PropertyOperator
}

export interface DataWarehousePersonPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.DataWarehousePersonProperty
    operator: PropertyOperator
}

export interface ErrorTrackingIssueFilter extends BasePropertyFilter {
    type: PropertyFilterType.ErrorTrackingIssue
    operator: PropertyOperator
}

/** Sync with plugin-server/src/types.ts */
export interface ElementPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Element
    key: 'tag_name' | 'text' | 'href' | 'selector'
    operator: PropertyOperator
}

export interface SessionPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Session
    operator: PropertyOperator
}

/** Sync with plugin-server/src/types.ts */
export interface CohortPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Cohort
    key: 'id'
    /**  @asType integer */
    value: number
    /** @default 'in' */
    operator: PropertyOperator
    cohort_name?: string
}

export interface GroupPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Group
    group_type_index?: integer | null
    operator: PropertyOperator
}

export interface LogPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Log
    operator: PropertyOperator
}

export interface FeaturePropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Feature
    operator: PropertyOperator
}

export interface FlagPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Flag
    /** Only flag_evaluates_to operator is allowed for flag dependencies */
    operator: PropertyOperator.FlagEvaluatesTo
    /** The key should be the flag ID */
    key: string
    /** The value can be true, false, or a variant name */
    value: boolean | string
}

export interface HogQLPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.HogQL
    key: string
}

export interface EmptyPropertyFilter {
    type?: never
    value?: never
    operator?: never
    key?: never
}

export type AnyPropertyFilter =
    | EventPropertyFilter
    | PersonPropertyFilter
    | ElementPropertyFilter
    | EventMetadataPropertyFilter
    | SessionPropertyFilter
    | CohortPropertyFilter
    | RecordingPropertyFilter
    | LogEntryPropertyFilter
    | GroupPropertyFilter
    | FeaturePropertyFilter
    | FlagPropertyFilter
    | HogQLPropertyFilter
    | EmptyPropertyFilter
    | DataWarehousePropertyFilter
    | DataWarehousePersonPropertyFilter
    | ErrorTrackingIssueFilter
    | LogPropertyFilter
    | RevenueAnalyticsPropertyFilter

/** Any filter type supported by `property_to_expr(scope="person", ...)`. */
export type AnyPersonScopeFilter =
    | PersonPropertyFilter
    | CohortPropertyFilter
    | HogQLPropertyFilter
    | EmptyPropertyFilter

export type AnyGroupScopeFilter = GroupPropertyFilter | HogQLPropertyFilter

export type AnyFilterLike = AnyPropertyFilter | PropertyGroupFilter | PropertyGroupFilterValue

export type SessionRecordingId = SessionRecordingType['id']

export interface RRWebRecordingConsoleLogPayload {
    level: LogLevel
    payload: (string | null)[]
    trace: string[]
}

export interface RRWebRecordingNetworkPayload {
    [key: number]: any
}

export interface RecordingConsoleLogBase {
    parsedPayload: string
    hash?: string // md5() on parsedPayload. Used for deduping console logs.
    count?: number // Number of duplicate console logs
    previewContent?: ReactNode // Content to show in first line
    fullContent?: ReactNode // Full content to show when item is expanded
    traceContent?: ReactNode // Url content to show on right side
    rawString: string // Raw text used for fuzzy search
    level: LogLevel
}

export type RecordingConsoleLog = RecordingConsoleLogBase & RecordingTimeMixinType

export type RecordingConsoleLogV2 = {
    timestamp: number
    windowId: string | undefined
    windowNumber?: number | '?' | undefined
    level: LogLevel
    content: string
    // JS code associated with the log - implicitly the empty array when not provided
    lines?: string[]
    // stack trace associated with the log - implicitly the empty array when not provided
    trace?: string[]
    // number of times this log message was seen - implicitly 1 when not provided
    count?: number
}

export interface RecordingSegment {
    kind: 'window' | 'buffer' | 'gap'
    startTimestamp: number // Epoch time that the segment starts
    endTimestamp: number // Epoch time that the segment ends
    durationMs: number
    windowId?: string
    isActive: boolean
    isLoading?: boolean
}

export type EncodedRecordingSnapshot = {
    windowId: string
    data: eventWithTime[]
}

// we can duplicate the name SnapshotSourceType for the object and the type
// since one only exists to be used in the other
// this way if we want to reference one of the valid string values for SnapshotSourceType
// we have a strongly typed way to do it
export const SnapshotSourceType = {
    blob: 'blob',
    file: 'file',
    blob_v2: 'blob_v2',
} as const

export type SnapshotSourceType = (typeof SnapshotSourceType)[keyof typeof SnapshotSourceType]

export interface SessionRecordingSnapshotSource {
    source: SnapshotSourceType
    start_timestamp?: string
    end_timestamp?: string
    blob_key?: string
}

export type SessionRecordingSnapshotParams = (
    | {
          source: 'blob'
          blob_key?: string
      }
    | {
          source: 'blob_v2'
          blob_key?: string
      }
    | {
          source: 'blob_v2'
          start_blob_key?: string
          end_blob_key?: string
      }
) & {
    decompress?: boolean
}

export interface SessionRecordingSnapshotSourceResponse {
    // v1 loaded each source separately
    source?: Pick<SessionRecordingSnapshotSource, 'source' | 'blob_key'> | 'processed'
    // with v2 we can load multiple sources at once
    sources?: Pick<SessionRecordingSnapshotSource, 'source' | 'blob_key'>[]
    snapshots?: RecordingSnapshot[]
    // we process snapshots to make them rrweb vanilla playable
    // this flag lets us skip reprocessing a source
    // the processed source is implicitly processed
    processed?: boolean
    // we only want to load each source from the API once
    // this flag is set when the API has loaded the source
    sourceLoaded?: boolean
}

export interface SessionRecordingSnapshotResponse {
    sources?: SessionRecordingSnapshotSource[]
    snapshots?: EncodedRecordingSnapshot[]
}

export type RecordingSnapshot = eventWithTime & {
    windowId: string
}

export interface SessionPlayerSnapshotData {
    snapshots?: RecordingSnapshot[]
    sources?: SessionRecordingSnapshotSource[]
    blob_keys?: string[]
}

export interface SessionPlayerData {
    person: PersonType | null
    segments: RecordingSegment[]
    bufferedToTime: number | null
    snapshotsByWindowId: Record<string, eventWithTime[]>
    durationMs: number
    start: Dayjs | null
    end: Dayjs | null
    fullyLoaded: boolean
    sessionRecordingId: SessionRecordingId
    sessionRetentionPeriodDays: number | null
}

export enum SessionRecordingUsageType {
    VIEWED = 'viewed',
    ANALYZED = 'analyzed',
    LOADED = 'loaded',
}

export enum SessionRecordingSidebarTab {
    OVERVIEW = 'overview',
    SESSION_SUMMARY = 'ai-summary',
    INSPECTOR = 'inspector',
    NETWORK_WATERFALL = 'network-waterfall',
}

export enum SessionRecordingSidebarStacking {
    Vertical = 'vertical',
    Horizontal = 'horizontal',
}

export enum SessionPlayerState {
    READY = 'ready',
    BUFFER = 'buffer',
    PLAY = 'play',
    PAUSE = 'pause',
    SCRUB = 'scrub',
    SKIP = 'skip',
    SKIP_TO_MATCHING_EVENT = 'skip_to_matching_event',
    ERROR = 'error',
}

export type AutoplayDirection = 'newer' | 'older' | null

/** Sync with plugin-server/src/types.ts */
export type ActionStepProperties =
    | EventPropertyFilter
    | PersonPropertyFilter
    | ElementPropertyFilter
    | CohortPropertyFilter

export interface RecordingPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Recording
    key: DurationType | 'snapshot_source' | 'visited_page' | 'comment_text'
    operator: PropertyOperator
}

export interface RecordingDurationFilter extends RecordingPropertyFilter {
    key: DurationType
    value: number
}

export interface LogEntryPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.LogEntry
    operator: PropertyOperator
}

export interface LogEntryPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.LogEntry
    operator: PropertyOperator
}

export interface LogEntryLevelFilter extends LogEntryPropertyFilter {
    key: 'level'
    value: FilterableLogLevel[]
}
export interface LogEntryMessageFilter extends LogEntryPropertyFilter {
    key: 'message'
    value: string
}

export type DurationType = 'duration' | 'active_seconds' | 'inactive_seconds'
export type FilterableLogLevel = 'info' | 'warn' | 'error'

export interface LegacyRecordingFilters {
    date_from?: string | null
    date_to?: string | null
    events?: FilterType['events']
    actions?: FilterType['actions']
    properties?: AnyPropertyFilter[]
    session_recording_duration?: RecordingDurationFilter
    duration_type_filter?: DurationType
    console_search_query?: LogEntryMessageFilter['value']
    console_logs?: LogEntryLevelFilter['value']
    snapshot_source?: AnyPropertyFilter | null
    filter_test_accounts?: boolean
    operand?: FilterLogicalOperator
}

export interface RecordingUniversalFilters {
    date_from?: string | null
    date_to?: string | null
    duration: RecordingDurationFilter[]
    filter_test_accounts?: boolean
    filter_group: UniversalFiltersGroup
    order?: RecordingsQuery['order']
    order_direction?: RecordingsQuery['order_direction']
}

export interface UniversalFiltersGroup {
    type: FilterLogicalOperator
    values: UniversalFiltersGroupValue[]
}

export type UniversalFiltersGroupValue = UniversalFiltersGroup | UniversalFilterValue
export type UniversalFilterValue = AnyPropertyFilter | ActionFilter

export type ErrorCluster = {
    cluster: number
    sample: string
    occurrences: number
    session_ids: string[]
    sparkline: Record<string, number>
    unique_sessions: number
    viewed: number
}
export type ErrorClusterResponse = ErrorCluster[] | null

export type EntityType = 'actions' | 'events' | 'data_warehouse' | 'new_entity'

export interface Entity {
    id: string | number
    name: string
    custom_name?: string
    order: number
    type: EntityType
}

export enum EntityTypes {
    ACTIONS = 'actions',
    EVENTS = 'events',
    DATA_WAREHOUSE = 'data_warehouse',
}

export type EntityFilter = {
    type?: EntityType
    id: Entity['id'] | null
    name?: string | null
    custom_name?: string | null
    index?: number
    order?: number
    optionalInFunnel?: boolean
}

export interface ActionFilter extends EntityFilter {
    math?: string
    math_property?: string | null
    math_property_type?: TaxonomicFilterGroupType | null
    math_group_type_index?: integer | null
    math_hogql?: string | null
    properties?: AnyPropertyFilter[]
    type: EntityType
    days?: string[] // TODO: why was this added here?
}

export interface DataWarehouseFilter extends ActionFilter {
    id_field: string
    timestamp_field: string
    distinct_id_field: string
    table_name: string
}

export const isDataWarehouseFilter = (filter: EntityFilter): filter is DataWarehouseFilter =>
    filter.type === EntityTypes.DATA_WAREHOUSE

export interface FunnelExclusionLegacy extends Partial<EntityFilter> {
    funnel_from_step: number
    funnel_to_step: number
}

export type EntityFilterTypes = EntityFilter | ActionFilter | null

export interface PersonType {
    id?: string
    uuid?: string
    name?: string
    distinct_ids: string[]
    properties: Record<string, any>
    created_at?: string
    is_identified?: boolean
}

export interface PersonListParams {
    properties?: AnyPropertyFilter[]
    search?: string
    cohort?: number
    distinct_id?: string
    include_total?: boolean // PostHog 3000-only
    limit?: number
}

export type SearchableEntity =
    | 'action'
    | 'cohort'
    | 'insight'
    | 'dashboard'
    | 'event_definition'
    | 'experiment'
    | 'feature_flag'
    | 'notebook'
    | 'survey'

export type SearchListParams = { q: string; entities?: SearchableEntity[] }

export type SearchResultType = {
    result_id: string
    type: SearchableEntity
    rank: number | null
    extra_fields: Record<string, unknown>
}

export type SearchResponse = {
    results: SearchResultType[]
    counts: Record<SearchableEntity, number | null>
}

export type GroupListParams = { group_type_index: GroupTypeIndex; search: string; limit?: number }

export type CreateGroupParams = {
    group_type_index: GroupTypeIndex
    group_key: string
    group_properties?: Record<string, any>
}

export interface MatchedRecordingEvent {
    uuid: string
    timestamp: string
}

export interface MatchedRecording {
    session_id?: string
    events: MatchedRecordingEvent[]
}

export interface CommonActorType {
    id: string | number
    properties: Record<string, any>
    /** @format date-time */
    created_at: string
    matched_recordings: MatchedRecording[]
    value_at_data_point: number | null
}

export interface PersonActorType extends CommonActorType {
    type: 'person'
    id: string
    name?: string
    distinct_ids: string[]
    is_identified: boolean
}

export interface GroupActorType extends CommonActorType {
    type: 'group'
    /** Group key. */
    id: string
    group_key: string
    group_type_index: integer
}

export type ActorType = PersonActorType | GroupActorType

export interface CohortGroupType {
    id: string
    days?: string
    action_id?: number
    event_id?: string
    label?: string
    count?: number
    count_operator?: string
    properties?: AnyPropertyFilter[]
    matchType: MatchType
    name?: string
}

// Synced with `posthog/models/property.py`
export interface CohortCriteriaType {
    id: string // Criteria filter id
    key: string
    value: BehavioralFilterType
    type: BehavioralFilterKey
    operator?: PropertyOperator | null
    group_type_index?: integer | null
    event_type?: TaxonomicFilterGroupType | null
    operator_value?: PropertyFilterValue
    time_value?: number | string | null
    time_interval?: TimeUnitType | null
    explicit_datetime?: string | null
    total_periods?: number | null
    min_periods?: number | null
    seq_event_type?: TaxonomicFilterGroupType | null
    seq_event?: string | number | null
    seq_time_value?: number | string | null
    seq_time_interval?: TimeUnitType | null
    negation?: boolean
    value_property?: string | null // Transformed into 'value' for api calls
    event_filters?: AnyPropertyFilter[] | null
    sort_key?: string // Client-side only stable id for sorting.
}

export type EmptyCohortGroupType = Partial<CohortGroupType>

export type EmptyCohortCriteriaType = Partial<CohortCriteriaType>

export type AnyCohortGroupType = CohortGroupType | EmptyCohortGroupType

export type AnyCohortCriteriaType = CohortCriteriaType | EmptyCohortCriteriaType

export type MatchType = typeof ENTITY_MATCH_TYPE | typeof PROPERTY_MATCH_TYPE

export interface CohortType {
    count?: number
    description?: string
    created_by?: UserBasicType | null
    created_at?: string
    deleted?: boolean
    id: number | 'new'
    is_calculating?: boolean
    errors_calculating?: number
    last_calculation?: string
    is_static?: boolean
    name?: string
    csv?: File
    groups: CohortGroupType[] // To be deprecated once `filter` takes over
    filters: {
        properties: CohortCriteriaGroupFilter
    }
    experiment_set?: number[]
    _create_in_folder?: string | null
    _create_static_person_ids?: string[]
}

export interface InsightHistory {
    id: number
    filters: Record<string, any>
    name?: string
    createdAt: string
    saved: boolean
    type: InsightType
}

export interface SavedFunnel extends InsightHistory {
    created_by: string
}

export type BinCountValue = number | typeof BIN_COUNT_AUTO

// https://github.com/PostHog/posthog/blob/master/posthog/constants.py#L106
export enum StepOrderValue {
    STRICT = 'strict',
    UNORDERED = 'unordered',
    ORDERED = 'ordered',
}

export enum PersonsTabType {
    FEED = 'feed',
    EVENTS = 'events',
    EXCEPTIONS = 'exceptions',
    SESSION_RECORDINGS = 'sessionRecordings',
    PROPERTIES = 'properties',
    COHORTS = 'cohorts',
    RELATED = 'related',
    HISTORY = 'history',
    FEATURE_FLAGS = 'featureFlags',
}

export enum GroupsTabType {
    FEED = 'feed',
    NOTES = 'notes',
    OVERVIEW = 'overview',
}

export enum LayoutView {
    Card = 'card',
    List = 'list',
}

export interface EventsTableAction {
    name: string
    id: string
}

export interface EventsTableRowItem {
    event?: EventType
    date_break?: string
    new_events?: boolean
}

export interface EventType {
    // fields from the API
    id: string
    distinct_id: string
    properties: Record<string, any>
    event: string
    timestamp: string
    person?: Pick<PersonType, 'is_identified' | 'distinct_ids' | 'properties'>
    elements: ElementType[]
    elements_chain?: string | null
    uuid?: string
    person_id?: string
    person_mode?: string
}

export interface LiveEvent {
    uuid: string
    event: string
    properties: Record<string, any>
    timestamp: string
    team_id: number
    distinct_id: string
    created_at: string
}

export interface RecordingTimeMixinType {
    playerTime: number | null
}

export interface RecordingEventType
    extends Pick<EventType, 'id' | 'event' | 'properties' | 'timestamp' | 'elements'>,
        RecordingTimeMixinType {
    fullyLoaded: boolean
    // allowing for absent distinct id which events don't
    distinct_id?: EventType['distinct_id']
}

export interface PlaylistCollectionCount {
    count: number
    watched_count: number
}

export interface PlaylistSavedFiltersCount {
    count: number
    watched_count: number
    has_more?: boolean
    increased?: boolean
    last_refreshed_at?: string
}

export interface PlaylistRecordingsCounts {
    saved_filters?: PlaylistSavedFiltersCount
    collection: PlaylistCollectionCount
}

export interface SessionRecordingPlaylistType {
    /** The primary key in the database, used as well in API endpoints */
    id: number
    short_id: string
    name: string
    derived_name?: string | null
    description?: string
    pinned?: boolean
    deleted: boolean
    created_at: string
    created_by: UserBasicType | null
    last_modified_at: string
    last_modified_by: UserBasicType | null
    filters?: LegacyRecordingFilters
    /**
     * the count of recordings matching filters, calculated periodically
     * and pinned recordings which is calculated in real-time
     * marked as has more if the filters count onoy matched one page and there are more available
     */
    recordings_counts?: PlaylistRecordingsCounts
    type: 'filters' | 'collection'
    /** Whether this playlist is a synthetic (virtual) playlist that's computed on-demand */
    is_synthetic?: boolean
    _create_in_folder?: string | null
}

export interface SavedSessionRecordingPlaylistsFilters {
    order: string
    search: string
    createdBy: number | 'All users'
    dateFrom: string | dayjs.Dayjs | undefined | null
    dateTo: string | dayjs.Dayjs | undefined | null
    page: number
    pinned: boolean
    type?: 'collection' | 'saved_filters'
    collectionType: 'custom' | 'synthetic' | 'new-urls' | null
}

export interface SavedSessionRecordingPlaylistsResult extends PaginatedResponse<SessionRecordingPlaylistType> {
    count: number
    /** not in the API response */
    filters?: SavedSessionRecordingPlaylistsFilters | null
}

export interface SessionRecordingSegmentType {
    start_time: string
    end_time: string
    window_id: string
    is_active: boolean
}

export interface SessionRecordingType {
    id: string
    /** Whether this recording has been viewed by you already. */
    viewed: boolean
    /** user ids of other users who have viewed this recording */
    viewers: string[]
    /** Length of recording in seconds. */
    recording_duration: number
    active_seconds?: number
    inactive_seconds?: number
    /** When the recording starts in ISO format. */
    start_time: string
    /** When the recording ends in ISO format. */
    end_time: string
    /** List of matching events. **/
    matching_events?: MatchedRecording[]
    distinct_id?: string
    email?: string
    person?: PersonType
    click_count?: number
    keypress_count?: number
    /** count of all mouse activity in the recording, not just clicks */
    mouse_activity_count?: number
    start_url?: string
    console_log_count?: number
    console_warn_count?: number
    console_error_count?: number
    /** Where this recording information was loaded from  */
    storage?: 'object_storage_lts' | 'object_storage'
    summary?: string
    snapshot_source: 'web' | 'mobile' | 'unknown'
    /** whether we have received data for this recording in the last 5 minutes
     * (assumes the recording was loaded from ClickHouse)
     * **/
    ongoing?: boolean
    /**
     * calculated on the backend so that we can sort by it, definition may change over time
     */
    activity_score?: number
    /** retention period for this recording */
    retention_period_days?: number
    /** When the recording expires, in ISO format. */
    expiry_time?: string
    /** Number of whole days left until the recording expires. */
    recording_ttl?: number
}

export interface SessionRecordingUpdateType {
    viewed?: boolean
    analyzed?: boolean
    player_metadata?: Record<string, any> | null
    durations?: Record<string, any> | null
    $pathname: string
}

export interface SessionRecordingPropertiesType {
    id: string
    properties?: Record<string, any>
}

export interface PerformancePageView {
    session_id: string
    pageview_id: string
    timestamp: string
}
export interface RecentPerformancePageView extends PerformancePageView {
    page_url: string
    duration: number
}

// copied from rrweb/network@1
export type Body =
    | string
    | Document
    | Blob
    | ArrayBufferView
    | ArrayBuffer
    | FormData
    | URLSearchParams
    | ReadableStream<Uint8Array>
    | null

/**
 * This is our base type for tracking network requests.
 * It sticks relatively closely to the spec for the web
 * see https://developer.mozilla.org/en-US/docs/Web/API/Performance_API
 * we have renamed/added a few fields for the benefit of ClickHouse
 * but don't yet clash with the spec
 */
export interface PerformanceEvent {
    uuid: string
    timestamp: string | number
    distinct_id: string
    session_id: string
    window_id: string
    pageview_id: string
    current_url: string

    // BASE_EVENT_COLUMNS
    time_origin?: string
    entry_type?: string
    name?: string

    // RESOURCE_EVENT_COLUMNS
    start_time?: number
    duration?: number
    redirect_start?: number
    redirect_end?: number
    worker_start?: number
    fetch_start?: number
    domain_lookup_start?: number
    domain_lookup_end?: number
    connect_start?: number
    secure_connection_start?: number
    connect_end?: number
    request_start?: number
    response_start?: number
    response_end?: number
    decoded_body_size?: number
    encoded_body_size?: number

    initiator_type?:
        | 'navigation'
        | 'css'
        | 'script'
        | 'xmlhttprequest'
        | 'fetch'
        | 'beacon'
        | 'video'
        | 'audio'
        | 'track'
        | 'img'
        | 'image'
        | 'input'
        | 'a'
        | 'iframe'
        | 'frame'
        | 'link'
        | 'other'
    next_hop_protocol?: string
    render_blocking_status?: string
    response_status?: number
    // see https://developer.mozilla.org/en-US/docs/Web/API/PerformanceResourceTiming/transferSize
    // zero has meaning for this field so should not be used unless the transfer size was known to be zero
    transfer_size?: number

    // LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS
    largest_contentful_paint_element?: string
    largest_contentful_paint_render_time?: number
    largest_contentful_paint_load_time?: number
    largest_contentful_paint_size?: number
    largest_contentful_paint_id?: string
    largest_contentful_paint_url?: string

    // NAVIGATION_EVENT_COLUMNS
    dom_complete?: number
    dom_content_loaded_event?: number
    dom_interactive?: number
    load_event_end?: number
    load_event_start?: number
    redirect_count?: number
    navigation_type?: string
    unload_event_end?: number
    unload_event_start?: number

    // Performance summary fields calculated on frontend
    first_contentful_paint?: number // https://web.dev/fcp/
    time_to_interactive?: number // https://web.dev/tti/
    total_blocking_time?: number // https://web.dev/tbt/
    web_vitals?: Set<RecordingEventType>

    // request/response capture - merged in from rrweb/network@1 payloads
    request_headers?: Record<string, string>
    response_headers?: Record<string, string>
    request_body?: Body
    response_body?: Body
    method?: string
    // normally, can rely on performance event values like duration,
    // but they may be absent in which case the SDK may have sent start and end time
    end_time?: number

    //rrweb/network@1 - i.e. not in ClickHouse table
    is_initial?: boolean
    raw?: Record<string, any>

    //server timings - reported as separate events but added back in here on the front end
    server_timings?: PerformanceEvent[]
}

export type AssetType = 'CSS' | 'JS' | 'Fetch' | 'Image' | 'Link' | 'XHR' | 'HTML'

export interface CurrentBillCycleType {
    current_period_start: number
    current_period_end: number
}

export type BillingFeatureType = {
    key: AvailableFeatureUnion
    name: string
    description?: string | null
    category?: string | null
    docsUrl?: string | null
    limit?: number | null
    note?: string | null
    unit?: string | null
    images?: {
        light: string
        dark: string
    } | null
    icon_key?: string | null
    entitlement_only?: boolean
    is_plan_default?: boolean
    type?: 'primary' | 'secondary' | null
}

export interface BillingTierType {
    flat_amount_usd: string
    unit_amount_usd: string
    current_amount_usd: string | null
    current_usage: number
    projected_usage: number | null
    projected_amount_usd: string | null
    up_to: number | null
}

export interface BillingTrialType {
    length: number
}

export interface BillingProductV2Type {
    type: string
    usage_key: string | null
    name: string
    headline: string | null
    description: string
    price_description?: string | null
    icon_key?: string | null
    image_url?: string | null
    screenshot_url: string | null
    docs_url: string
    free_allocation?: number | null
    subscribed: boolean | null
    tiers?: BillingTierType[] | null
    tiered: boolean
    current_usage?: number
    projected_amount_usd?: string | null
    projected_amount_usd_with_limit?: string | null
    projected_usage?: number
    percentage_usage: number
    current_amount_usd_before_addons: string | null
    current_amount_usd: string | null
    usage_limit: number | null
    has_exceeded_limit: boolean
    unit: string | null
    unit_amount_usd: string | null
    plans: BillingPlanType[]
    contact_support: boolean | null
    inclusion_only: any
    features: BillingFeatureType[]
    addons: BillingProductV2AddonType[]
    // addons-only: if this addon is included with the base product and not subscribed individually. for backwards compatibility.
    included_with_main_product?: boolean
    trial?: BillingTrialType | null
    legacy_product?: boolean | null
}

export interface BillingProductV2AddonType {
    name: string
    description: string
    price_description: string | null
    image_url: string | null
    icon_key?: string
    docs_url: string | null
    type: string
    tiers: BillingTierType[] | null
    tiered: boolean
    subscribed: boolean
    // sometimes addons are included with the base product, but they aren't subscribed individually
    included_with_main_product?: boolean
    inclusion_only: boolean | null
    contact_support: boolean | null
    unit: string | null
    unit_amount_usd: string | null
    current_amount_usd: string | null
    current_usage: number
    projected_usage: number | null
    projected_amount_usd: string | null
    plans: BillingPlanType[]
    usage_key?: string
    free_allocation?: number | null
    percentage_usage?: number
    features: BillingFeatureType[]
    included_if?:
        | 'no_active_subscription'
        | 'has_subscription'
        | 'no_active_parent_subscription'
        | 'has_parent_subscription'
        | null
    usage_limit?: number | null
    trial?: BillingTrialType | null
    legacy_product?: boolean | null
}
export interface BillingType {
    customer_id: string
    has_active_subscription: boolean
    subscription_level: 'free' | 'paid' | 'custom'
    free_trial_until?: Dayjs
    stripe_portal_url?: string
    deactivated?: boolean
    current_total_amount_usd?: string
    current_total_amount_usd_after_discount?: string
    projected_total_amount_usd?: string
    projected_total_amount_usd_after_discount?: string
    projected_total_amount_usd_with_limit?: string
    projected_total_amount_usd_with_limit_after_discount?: string
    products: BillingProductV2Type[]

    custom_limits_usd?: {
        [key: string]: number | null
    }
    next_period_custom_limits_usd?: {
        [key: string]: number | null
    }
    billing_period?: {
        current_period_start: Dayjs
        current_period_end: Dayjs
        interval: 'month' | 'year'
    }
    license?: {
        plan: LicensePlan
    }
    available_plans?: BillingPlanType[]
    discount_percent?: number
    discount_amount_usd?: string
    amount_off_expires_at?: Dayjs
    trial?: {
        type: 'autosubscribe' | 'standard'
        status: 'active' | 'expired' | 'cancelled' | 'converted'
        target: 'paid' | 'teams' | 'enterprise'
        expires_at: string
    }
    billing_plan: BillingPlan | null
    startup_program_label?: StartupProgramLabel | null
    startup_program_label_previous?: StartupProgramLabel | null
    is_annual_plan_customer?: boolean | null
    account_owner?: {
        email?: string
        name?: string
    }
}

export interface BillingPeriod {
    start: Dayjs | null
    end: Dayjs | null
    interval: 'month' | 'year' | null
}

export interface BillingPlanType {
    free_allocation?: number | null
    features: BillingFeatureType[]
    name: string
    description: string
    is_free?: boolean
    plan_key?: string
    image_url: string | null
    docs_url: string | null
    note: string | null
    unit: string | null
    flat_rate: boolean
    product_key: ProductKeyUnion
    current_plan?: boolean | null
    tiers?: BillingTierType[] | null
    unit_amount_usd: string | null
    included_if?:
        | 'no_active_subscription'
        | 'has_subscription'
        | 'no_active_parent_subscription'
        | 'has_parent_subscription'
        | null
    initial_billing_limit?: number | null
    contact_support: boolean | null
}

export interface PlanInterface {
    key: string
    name: string
    custom_setup_billing_message: string
    image_url: string
    self_serve: boolean
    is_metered_billing: boolean
    event_allowance: number
    price_string: string
}

// Creating a nominal type: https://github.com/microsoft/TypeScript/issues/202#issuecomment-961853101
export type InsightShortId = string & { readonly '': unique symbol }

export enum InsightColor {
    White = 'white',
    Black = 'black',
    Blue = 'blue',
    Green = 'green',
    Purple = 'purple',
}

export interface Cacheable {
    last_refresh: string | null
    next_allowed_client_refresh?: string | null
    cache_target_age?: string | null
}

export interface TileLayout extends Omit<Layout, 'i'> {
    i?: string // we use `i` in the front end but not in the API
}

export interface Tileable {
    layouts?: Record<DashboardLayoutSize, TileLayout> | Record<string, never> // allow an empty object or one with DashboardLayoutSize keys
    color: InsightColor | null
}

export interface DashboardTile<T = InsightModel> extends Tileable {
    id: number
    insight?: T
    text?: TextModel
    deleted?: boolean
    is_cached?: boolean
    order?: number
    error?: {
        type: string
        message: string
    }
    filters_overrides?: TileFilters
}

export interface DashboardTileBasicType {
    id: number
    dashboard_id: number
    deleted?: boolean
}

export interface TextModel {
    body: string
    created_by?: UserBasicType
    last_modified_by?: UserBasicType
    last_modified_at: string
}

export interface InsightModel extends Cacheable, WithAccessControl {
    /** The unique key we use when communicating with the user, e.g. in URLs */
    short_id: InsightShortId
    /** The primary key in the database, used as well in API endpoints */
    id: number
    name: string
    derived_name?: string | null
    description?: string
    favorited?: boolean
    order: number | null
    result: any
    deleted: boolean
    saved: boolean
    created_at: string
    created_by: UserBasicType | null
    is_sample: boolean
    /** @deprecated Use `dashboard_tiles` instead */
    dashboards: number[] | null
    dashboard_tiles: DashboardTileBasicType[] | null
    updated_at: string
    tags?: string[]
    last_modified_at: string
    last_modified_by: UserBasicType | null
    last_viewed_at?: string | null
    timezone?: string | null
    /** Only used in the frontend to store the next breakdown url */
    next?: string
    /** Only used in the frontend to toggle showing Baseline in funnels or not */
    disable_baseline?: boolean
    filters: Partial<FilterType>
    alerts?: AlertType[]
    query?: Node | null
    query_status?: QueryStatus
    /** Only used when creating objects */
    _create_in_folder?: string | null
}

export interface QueryBasedInsightModel extends Omit<InsightModel, 'filters'> {
    query: Node | null
}

export interface EndpointVersion {
    id: string
    version: number
    query: HogQLQuery | InsightQueryNode
    created_at: string
    created_by: UserBasicType | null
    change_summary: string
}

export interface EndpointType extends WithAccessControl {
    id: string
    name: string
    description: string
    query: HogQLQuery | InsightQueryNode
    parameters: Record<string, any>
    is_active: boolean
    endpoint_path: string
    created_at: string
    updated_at: string
    created_by: UserBasicType | null
    cache_age_seconds: number
    is_materialized: boolean
    current_version: number
    versions_count: number
    /** Purely local value to determine whether the query endpoint should be highlighted, e.g. as a fresh duplicate. */
    _highlight?: boolean
    /** Last execution time from ClickHouse query_log table */
    last_executed_at?: string
    materialization?: EndpointMaterializationType
}

export interface EndpointMaterializationType {
    can_materialize: boolean
    reason?: string
    status?: string
    error?: string
    last_materialized_at?: string
    sync_frequency?: DataWarehouseSyncInterval
}

export interface DashboardBasicType extends WithAccessControl {
    id: number
    name: string
    description: string
    pinned: boolean
    created_at: string
    created_by: UserBasicType | null
    last_accessed_at: string | null
    last_viewed_at?: string | null
    is_shared: boolean
    deleted: boolean
    creation_mode: 'default' | 'template' | 'duplicate' | 'unlisted'
    tags?: string[]
    /** Purely local value to determine whether the dashboard should be highlighted, e.g. as a fresh duplicate. */
    _highlight?: boolean
    /**
     * The last time the dashboard was refreshed.
     * Used to block the dashboard refresh button.
     */
    last_refresh?: string | null
}

export interface DashboardTemplateListParams {
    scope?: DashboardTemplateScope
    // matches on template name, description, and tags
    search?: string
}

export type DashboardTemplateScope = 'team' | 'global' | 'feature_flag'

export interface DashboardType<T = InsightModel> extends DashboardBasicType {
    tiles: DashboardTile<T>[]
    filters: DashboardFilter
    variables?: Record<string, HogQLVariable>
    persisted_filters?: DashboardFilter | null
    persisted_variables?: Record<string, HogQLVariable> | null
    breakdown_colors?: BreakdownColorConfig[]
    data_color_theme_id?: number | null
}

export enum TemplateAvailabilityContext {
    GENERAL = 'general',
    ONBOARDING = 'onboarding',
}

export interface DashboardTemplateType<T = InsightModel> {
    id: string
    team_id?: number
    created_at?: string
    template_name: string
    dashboard_description?: string
    dashboard_filters?: DashboardFilter
    tiles: DashboardTile<T>[]
    variables?: DashboardTemplateVariableType[]
    tags?: string[]
    image_url?: string
    scope?: DashboardTemplateScope
    availability_contexts?: TemplateAvailabilityContext[]
}

export interface MonacoMarker {
    message: string
}

// makes the DashboardTemplateType properties optional and the tiles properties optional
export type DashboardTemplateEditorType = Partial<Omit<DashboardTemplateType, 'tiles'>> & {
    tiles: Partial<DashboardTile>[]
}

export interface DashboardTemplateVariableType {
    id: string
    name: string
    description: string
    type: 'event'
    default: TemplateVariableStep
    required: boolean
    touched?: boolean
    selector?: string
    href?: string
    url?: string
}

export type DashboardLayoutSize = 'sm' | 'xs'

export interface OrganizationInviteType {
    id: string
    target_email: string
    first_name: string
    level: OrganizationMembershipLevel
    is_expired: boolean
    emailing_attempt_made: boolean
    created_by: UserBasicType | null
    created_at: string
    updated_at: string
    message?: string
    private_project_access?: Array<{ id: number; level: AccessControlLevel.Member | AccessControlLevel.Admin }>
}

export enum PluginInstallationType {
    Local = 'local',
    Custom = 'custom',
    Repository = 'repository',
    Source = 'source',
    Inline = 'inline',
}

export interface PluginType {
    id: number
    plugin_type: PluginInstallationType
    name: string
    description?: string
    url?: string
    tag?: string
    icon?: string
    latest_tag?: string // apps management page: The latest git hash for the repo behind the url
    config_schema: Record<string, PluginConfigSchema> | PluginConfigSchema[]
    source?: string
    maintainer?: string
    is_global: boolean
    organization_id: string
    organization_name: string
    metrics?: Record<string, StoredMetricMathOperations>
    capabilities?: Record<'jobs' | 'methods' | 'scheduled_tasks', string[] | undefined>
    public_jobs?: Record<string, JobSpec>
    hog_function_migration_available?: boolean
}

export type AppType = PluginType

/** Config passed to app component and logic as props. Sent in Django's app context */
export interface FrontendAppConfig {
    pluginId: number
    pluginConfigId: number
    pluginType: PluginInstallationType | null
    name: string
    url: string
    config: Record<string, any>
}

/** Frontend app created after receiving a bundle via import('').getFrontendApp() */
export interface FrontendApp {
    id: number
    pluginId: number
    error?: any
    title?: string
    logic?: LogicWrapper
    component?: (props: FrontendAppConfig) => JSX.Element
    onInit?: (props: FrontendAppConfig) => void
}

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

/** @deprecated in favor of PluginConfigTypeNew */
export interface PluginConfigType {
    id?: number
    plugin: number
    team_id: number
    enabled: boolean
    order: number

    config: Record<string, any>
    error?: PluginErrorType
    delivery_rate_24h?: number | null
    created_at?: string
}

/** @deprecated in favor of PluginConfigWithPluginInfoNew */
export interface PluginConfigWithPluginInfo extends PluginConfigType {
    id: number
    plugin_info: PluginType
}

// TODO: Rename to PluginConfigType once the legacy PluginConfigType are removed from the frontend
export interface PluginConfigTypeNew {
    id: number
    plugin: number
    team_id: number
    enabled: boolean
    order: number
    name: string
    description?: string
    updated_at: string
    delivery_rate_24h?: number | null
    config: Record<string, any>
}

// TODO: Rename to PluginConfigWithPluginInfo once the are removed from the frontend
export interface PluginConfigWithPluginInfoNew extends PluginConfigTypeNew {
    plugin_info: PluginType
}

export interface PluginErrorType {
    message: string
    time: string
    stack?: string
    name?: string
    event?: Record<string, any>
}

export type LogEntryLevel = 'DEBUG' | 'LOG' | 'INFO' | 'WARN' | 'WARNING' | 'ERROR'

// The general log entry format that eventually everything should match
export type LogEntry = {
    log_source_id: string
    instance_id: string
    timestamp: string
    level: LogEntryLevel
    message: string
}

export type LogEntryRequestParams = {
    limit?: number
    after?: string
    before?: string
    // Comma separated list of log levels
    level?: string
    search?: string
    instance_id?: string
}

export interface PluginLogEntry {
    id: string
    team_id: number
    plugin_id: number
    plugin_config_id: number
    timestamp: string
    source: string
    type: LogEntryLevel
    is_system: boolean
    message: string
    instance_id: string
}

export enum AnnotationScope {
    Insight = 'dashboard_item',
    Dashboard = 'dashboard',
    Project = 'project',
    Organization = 'organization',
}

export interface RawAnnotationType {
    id: number
    scope: AnnotationScope
    content: string | null
    date_marker: string | null
    created_by?: UserBasicType | null
    created_at: string
    updated_at: string
    dashboard_item?: number | null
    insight_short_id?: QueryBasedInsightModel['short_id'] | null
    insight_name?: QueryBasedInsightModel['name'] | null
    insight_derived_name?: QueryBasedInsightModel['derived_name'] | null
    dashboard_id?: DashboardBasicType['id'] | null
    dashboard_name?: DashboardBasicType['name'] | null
    deleted?: boolean
    creation_type?: 'USR' | 'GIT'
}

export interface AnnotationType extends Omit<RawAnnotationType, 'created_at' | 'date_marker'> {
    date_marker: dayjs.Dayjs | null
    created_at: dayjs.Dayjs
}

export interface DatedAnnotationType extends Omit<AnnotationType, 'date_marker'> {
    date_marker: dayjs.Dayjs
}

export enum ChartDisplayType {
    ActionsLineGraph = 'ActionsLineGraph',
    // TODO: remove this as ActionsBar was meant to be for unstacked bar charts
    // but with current logic for all insights with this setting saved in the query
    // we still show them stacked bars
    ActionsBar = 'ActionsBar',
    ActionsUnstackedBar = 'ActionsUnstackedBar',
    ActionsStackedBar = 'ActionsStackedBar',
    ActionsAreaGraph = 'ActionsAreaGraph',
    ActionsLineGraphCumulative = 'ActionsLineGraphCumulative',
    BoldNumber = 'BoldNumber',
    ActionsPie = 'ActionsPie',
    ActionsBarValue = 'ActionsBarValue',
    ActionsTable = 'ActionsTable',
    WorldMap = 'WorldMap',
    CalendarHeatmap = 'CalendarHeatmap',
}
export enum ChartDisplayCategory {
    TimeSeries = 'TimeSeries',
    CumulativeTimeSeries = 'CumulativeTimeSeries',
    TotalValue = 'TotalValue',
}

export type BreakdownType =
    | 'cohort'
    | 'person'
    | 'event'
    | 'event_metadata'
    | 'group'
    | 'session'
    | 'hogql'
    | 'data_warehouse'
    | 'data_warehouse_person_property'
    | 'revenue_analytics'
export type IntervalType = 'second' | 'minute' | 'hour' | 'day' | 'week' | 'month'
export type SimpleIntervalType = 'day' | 'month'
export type SmoothingType = number
export type InsightSceneSource = 'web-analytics' | 'llm-analytics'

export enum InsightType {
    TRENDS = 'TRENDS',
    STICKINESS = 'STICKINESS',
    LIFECYCLE = 'LIFECYCLE',
    FUNNELS = 'FUNNELS',
    RETENTION = 'RETENTION',
    PATHS = 'PATHS',
    JSON = 'JSON',
    SQL = 'SQL',
    HOG = 'HOG',
}

export enum PathType {
    PageView = '$pageview',
    Screen = '$screen',
    CustomEvent = 'custom_event',
    HogQL = 'hogql',
}

export enum FunnelPathType {
    before = 'funnel_path_before_step',
    between = 'funnel_path_between_steps',
    after = 'funnel_path_after_step',
}

export enum FunnelVizType {
    Steps = 'steps',
    TimeToConvert = 'time_to_convert',
    Trends = 'trends',
}

export type RetentionType =
    | typeof RETENTION_RECURRING
    | typeof RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS
    | typeof RETENTION_FIRST_EVER_OCCURRENCE

export enum RetentionPeriod {
    Hour = 'Hour',
    Day = 'Day',
    Week = 'Week',
    Month = 'Month',
}

export type SlowQueryPossibilities = 'all_events' | 'large_date_range' | 'first_time_for_user' | 'strict_funnel'

export type BreakdownKeyType = integer | string | number | (integer | string | number)[] | null

/**
 * Legacy breakdown.
 */
export interface Breakdown {
    property: string | number
    type: BreakdownType
    normalize_url?: boolean
    histogram_bin_count?: number
    group_type_index?: number
}

export interface FilterType {
    // used by all
    from_dashboard?: boolean | number
    insight?: InsightType
    filter_test_accounts?: boolean
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    sampling_factor?: number | null

    date_from?: string | null
    date_to?: string | null
    /**
     * Whether the `date_from` and `date_to` should be used verbatim. Disables rounding to the start and end of period.
     * Strings are cast to bools, e.g. "true" -> true.
     */
    explicit_date?: boolean | string | null

    events?: Record<string, any>[]
    actions?: Record<string, any>[]
    data_warehouse?: Record<string, any>[]
    new_entity?: Record<string, any>[]

    // persons modal
    entity_id?: string | number
    entity_type?: EntityType
    entity_math?: string

    // used by trends and stickiness
    interval?: IntervalType
    // TODO: extract into TrendsFunnelsCommonFilterType
    breakdown_type?: BreakdownType | null
    breakdown?: BreakdownKeyType
    breakdown_normalize_url?: boolean
    breakdowns?: Breakdown[]
    breakdown_group_type_index?: integer | null
    breakdown_hide_other_aggregation?: boolean | null
    breakdown_limit?: integer | null
    aggregation_group_type_index?: integer // Groups aggregation
}

export interface TemplateVariableStep {
    id?: string
    math?: BaseMathType
    name?: string | null
    order?: number
    type?: EntityTypes
    event?: string
    selector?: string | null
    href?: string | null
    url?: string | null
    properties?: Record<string, any>[]
    custom_name?: string
    custom_event?: boolean
}

export interface PropertiesTimelineFilterType {
    date_from?: string | null // DateMixin
    date_to?: string | null // DateMixin
    interval?: IntervalType // IntervalMixin
    properties?: AnyPropertyFilter[] | PropertyGroupFilter // PropertyMixin
    events?: Record<string, any>[] // EntitiesMixin
    actions?: Record<string, any>[] // EntitiesMixin
    aggregation_group_type_index?: number // GroupsAggregationMixin
    display?: ChartDisplayType // DisplayDerivedMixin
    breakdown_type?: BreakdownType | null
    breakdown?: BreakdownKeyType
}

export interface TrendsFilterType extends FilterType {
    // Specifies that we want to smooth the aggregation over the specified
    // number of intervals, e.g. for a day interval, we may want to smooth over
    // 7 days to remove weekly variation. Smoothing is performed as a moving average.
    smoothing_intervals?: number
    formula?: string
    compare_to?: string
    compare?: boolean
    /** @deprecated */
    shown_as?: ShownAsValue
    display?: ChartDisplayType
    breakdown_histogram_bin_count?: number // trends breakdown histogram bin count

    // frontend only
    show_alert_threshold_lines?: boolean // used to show/hide horizontal lines on insight representing alert thresholds set on the insight
    show_legend?: boolean // used to show/hide legend next to insights graph
    hidden_legend_keys?: Record<string, boolean | undefined> // used to toggle visibilities in table and legend
    aggregation_axis_format?: AggregationAxisFormat // a fixed format like duration that needs calculation
    aggregation_axis_prefix?: string // a prefix to add to the aggregation axis e.g. £
    aggregation_axis_postfix?: string // a postfix to add to the aggregation axis e.g. %
    decimal_places?: number
    min_decimal_places?: number
    show_values_on_series?: boolean
    show_labels_on_series?: boolean
    show_percent_stack_view?: boolean
    y_axis_scale_type?: 'log10' | 'linear'
    show_multiple_y_axes?: boolean
}

export interface StickinessFilterType extends FilterType {
    compare_to?: string
    compare?: boolean
    /** @deprecated */
    shown_as?: ShownAsValue
    display?: ChartDisplayType

    // frontend only
    show_legend?: boolean // used to show/hide legend next to insights graph
    hidden_legend_keys?: Record<string, boolean | undefined> // used to toggle visibilities in table and legend
    show_values_on_series?: boolean
    show_multiple_y_axes?: boolean

    // persons only
    stickiness_days?: number
}

export interface FunnelsFilterType extends FilterType {
    funnel_viz_type?: FunnelVizType // parameter sent to funnels API for time conversion code path
    funnel_from_step?: number // used in time to convert: initial step index to compute time to convert
    funnel_to_step?: number // used in time to convert: ending step index to compute time to convert
    breakdown_attribution_type?: BreakdownAttributionType // funnels breakdown attribution type
    breakdown_attribution_value?: number // funnels breakdown attribution specific step value
    bin_count?: BinCountValue // used in time to convert: number of bins to show in histogram
    funnel_window_interval_unit?: FunnelConversionWindowTimeUnit // minutes, days, weeks, etc. for conversion window
    funnel_window_interval?: number | undefined // length of conversion window
    funnel_order_type?: StepOrderValue
    exclusions?: FunnelExclusionLegacy[] // used in funnel exclusion filters
    funnel_aggregate_by_hogql?: string | null

    // frontend only
    layout?: FunnelLayout // used only for funnels
    funnel_step_reference?: FunnelStepReference // whether conversion shown in graph should be across all steps or just from the previous step
    hidden_legend_keys?: Record<string, boolean | undefined> // used to toggle visibilities in table and legend

    // persons only
    entrance_period_start?: string // this and drop_off is used for funnels time conversion date for the persons modal
    drop_off?: boolean
    funnel_step?: number
    funnel_step_breakdown?: string | number[] | number | null // used in steps breakdown: persons modal
    funnel_custom_steps?: number[] // used to provide custom steps for which to get people in a funnel - primarily for correlation use
    funnel_correlation_person_entity?: Record<string, any> // Funnel Correlation Persons Filter
    funnel_correlation_person_converted?: 'true' | 'false' // Funnel Correlation Persons Converted - success or failure counts
}
export interface PathsFilterType extends FilterType {
    path_type?: PathType
    paths_hogql_expression?: string
    include_event_types?: PathType[]
    start_point?: string
    end_point?: string
    path_groupings?: string[]
    funnel_paths?: FunnelPathType
    funnel_filter?: Record<string, any> // Funnel Filter used in Paths
    exclude_events?: string[] // Paths Exclusion type
    /** @asType integer */
    step_limit?: number // Paths Step Limit
    path_replacements?: boolean
    local_path_cleaning_filters?: PathCleaningFilter[] | null
    /** @asType integer */
    edge_limit?: number | undefined // Paths edge limit
    /** @asType integer */
    min_edge_weight?: number | undefined // Paths
    /** @asType integer */
    max_edge_weight?: number | undefined // Paths

    // persons only
    path_start_key?: string // Paths People Start Key
    path_end_key?: string // Paths People End Key
    path_dropoff_key?: string // Paths People Dropoff Key
}

export type RetentionEntityKind = NodeKind.ActionsNode | NodeKind.EventsNode

export interface RetentionEntity {
    id?: string | number // TODO: Fix weird typing issues
    kind?: RetentionEntityKind
    name?: string
    type?: EntityType
    /**  @asType integer */
    order?: number
    uuid?: string
    custom_name?: string
    /** filters on the event */
    properties?: AnyPropertyFilter[]
}

export enum RetentionDashboardDisplayType {
    TableOnly = 'table_only',
    GraphOnly = 'graph_only',
    All = 'all',
}

export interface RetentionFilterType extends FilterType {
    retention_type?: RetentionType
    /** Whether retention is with regard to initial cohort size, or that of the previous period. */
    retention_reference?: 'total' | 'previous'
    /**
     * @asType integer
     */
    total_intervals?: number
    returning_entity?: RetentionEntity
    target_entity?: RetentionEntity
    period?: RetentionPeriod
    cumulative?: boolean

    //frontend only
    show_mean?: boolean // deprecated
    mean_retention_calculation?: 'simple' | 'weighted' | typeof RETENTION_MEAN_NONE
}
export interface LifecycleFilterType extends FilterType {
    /** @deprecated */
    shown_as?: ShownAsValue

    // frontend only
    show_legend?: boolean
    show_values_on_series?: boolean
    toggledLifecycles?: LifecycleToggle[]
}

export type LifecycleToggle = 'new' | 'resurrecting' | 'returning' | 'dormant'
export type AnyFilterType =
    | TrendsFilterType
    | StickinessFilterType
    | FunnelsFilterType
    | PathsFilterType
    | RetentionFilterType
    | LifecycleFilterType
    | FilterType

export type AnyPartialFilterType =
    | Partial<TrendsFilterType>
    | Partial<StickinessFilterType>
    | Partial<FunnelsFilterType>
    | Partial<PathsFilterType>
    | Partial<RetentionFilterType>
    | Partial<LifecycleFilterType>
    | Partial<FilterType>

export interface EventsListQueryParams {
    event?: string
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    orderBy?: string[]
    action_id?: number
    after?: string
    before?: string
    limit?: number
    offset?: number
}

export interface RecordingEventsFilters {
    query: string
}

export interface RecordingConsoleLogsFilters {
    query: string
}

export enum RecordingWindowFilter {
    All = 'all',
}

export interface EditorFilterProps {
    insightProps: InsightLogicProps
}

export interface InsightEditorFilter {
    key: string
    label?: string | ((props: EditorFilterProps) => JSX.Element | null)
    tooltip?: JSX.Element
    showOptional?: boolean
    /** Editor filter component. Cannot be an anonymous function or the key would not work! */
    component?: (props: EditorFilterProps) => JSX.Element | null
}

export type InsightEditorFilterGroup = {
    title: string
    editorFilters: InsightEditorFilter[]
    defaultExpanded?: boolean
}

export interface SystemStatusSubrows {
    columns: string[]
    rows: string[][]
}

export interface SystemStatusRow {
    metric: string
    value: boolean | string | number | null
    key: string
    description?: string
    subrows?: SystemStatusSubrows
}

export interface SystemStatus {
    overview: SystemStatusRow[]
}

export type QuerySummary = { duration: string } & Record<string, string>

export interface SystemStatusQueriesResult {
    postgres_running: QuerySummary[]
    clickhouse_running?: QuerySummary[]
    clickhouse_slow_log?: QuerySummary[]
}

export interface SystemStatusAnalyzeResult {
    query: string
    timing: {
        query_id: string
        event_time: string
        query_duration_ms: number
        read_rows: number
        read_size: string
        result_rows: number
        result_size: string
        memory_usage: string
    }
    flamegraphs: Record<string, string>
}

export interface TrendAPIResponse<ResultType = TrendResult[]> {
    type: 'Trends'
    is_cached: boolean
    last_refresh: string | null
    result: ResultType
    timezone: string
    next: string | null
}

export interface TrendResult {
    action: ActionFilter
    actions?: ActionFilter[]
    count: number
    data: number[]
    days: string[]
    dates?: string[]
    label: string
    labels: string[]
    breakdown_value?: string | number | string[]
    aggregated_value: number
    status?: string
    compare_label?: CompareLabelType
    compare?: boolean
    persons_urls?: { url: string }[]
    persons?: Person
    filter?: TrendsFilterType
}

interface Person {
    url: string
    filter: Partial<FilterType>
}

export interface FunnelStep {
    // The type returned from the API.
    action_id: string
    average_conversion_time: number | null
    median_conversion_time: number | null
    count: number
    name: string
    custom_name?: string | null
    order: number
    people?: string[]
    type: EntityType
    labels?: string[]
    breakdown?: BreakdownKeyType
    breakdowns?: BreakdownKeyType[]
    breakdown_value?: BreakdownKeyType
    data?: number[]
    days?: string[]

    /** Url that you can GET to retrieve the people that converted in this step */
    converted_people_url: string

    /** Url that you can GET to retrieve the people that dropped in this step  */
    dropped_people_url: string | null
}

export interface FunnelsTimeConversionBins {
    bins: [number, number][]
    average_conversion_time: number | null
}

export type FunnelResultType = FunnelStep[] | FunnelStep[][] | FunnelsTimeConversionBins

export interface FunnelAPIResponse<ResultType = FunnelResultType> {
    is_cached: boolean
    last_refresh: string | null
    result: ResultType
    timezone: string
}

export interface FunnelStepWithNestedBreakdown extends FunnelStep {
    nested_breakdown?: FunnelStep[]
}

export interface FunnelTimeConversionMetrics {
    averageTime: number
    stepRate: number
    totalRate: number
}

export interface FunnelConversionWindow {
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit
    funnelWindowInterval: number
}

// https://github.com/PostHog/posthog/blob/master/posthog/models/filters/mixins/funnel.py#L100
export enum FunnelConversionWindowTimeUnit {
    Second = 'second',
    Minute = 'minute',
    Hour = 'hour',
    Day = 'day',
    Week = 'week',
    Month = 'month',
}

export enum FunnelStepReference {
    total = 'total',
    previous = 'previous',
}

export interface FunnelStepWithConversionMetrics extends FunnelStep {
    droppedOffFromPrevious: number
    conversionRates: {
        fromPrevious: number
        total: number
        fromBasisStep: number // either fromPrevious or total, depending on FunnelStepReference
    }
    nested_breakdown?: Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'>[]
    rowKey?: number | string
    significant?: {
        fromPrevious: boolean
        total: boolean
        fromBasisStep: boolean // either fromPrevious or total, depending on FunnelStepReference
    }
}

export interface FlattenedFunnelStepByBreakdown {
    rowKey: number | string
    isBaseline?: boolean
    breakdown?: BreakdownKeyType
    // :KLUDGE: Data transforms done in `getBreakdownStepValues`
    breakdown_value?: Array<string | number>
    breakdownIndex?: number
    conversionRates?: {
        total: number
    }
    steps?: FunnelStepWithConversionMetrics[]
    significant?: boolean
}

export interface FunnelCorrelation {
    event: Pick<EventType, 'elements' | 'event' | 'properties'>
    odds_ratio: number
    success_count: number
    success_people_url: string
    failure_count: number
    failure_people_url: string
    correlation_type: FunnelCorrelationType.Failure | FunnelCorrelationType.Success
    result_type:
        | FunnelCorrelationResultsType.Events
        | FunnelCorrelationResultsType.Properties
        | FunnelCorrelationResultsType.EventWithProperties
}

export enum FunnelCorrelationType {
    Success = 'success',
    Failure = 'failure',
}

export enum FunnelCorrelationResultsType {
    Events = 'events',
    Properties = 'properties',
    EventWithProperties = 'event_with_properties',
}

export enum BreakdownAttributionType {
    FirstTouch = 'first_touch',
    LastTouch = 'last_touch',
    AllSteps = 'all_events',
    Step = 'step',
}

export interface ChartParams {
    inCardView?: boolean
    inSharedMode?: boolean
    showPersonsModal?: boolean
    /** allows overriding by queries, e.g. setting empty state text*/
    context?: QueryContext<InsightVizNode>
}

export interface HistogramGraphDatum {
    id: number
    bin0: number
    bin1: number
    count: number
    label: string
}

// Shared between insightLogic, dashboardItemLogic, trendsLogic, funnelLogic, pathsLogic, retentionLogic
export interface InsightLogicProps<Q extends QuerySchema = QuerySchema> {
    /** currently persisted insight */
    dashboardItemId?: InsightShortId | 'new' | `new-${string}` | null
    /** id of the dashboard the insight is on (when the insight is being displayed on a dashboard) **/
    dashboardId?: DashboardType['id']
    /** cached insight */
    cachedInsight?: Partial<QueryBasedInsightModel> | null
    /** enable this to avoid API requests */
    doNotLoad?: boolean
    loadPriority?: number
    onData?: (data: Record<string, unknown> | null | undefined) => void
    /** query when used as ad-hoc insight */
    query?: Q
    setQuery?: (node: Q) => void

    /** Used to group DataNodes into a collection for group operations like refreshAll **/
    dataNodeCollectionId?: string

    /** Dashboard filters to override the ones in the query */
    filtersOverride?: DashboardFilter | null
    /** Dashboard variables to override the ones in the query */
    variablesOverride?: Record<string, HogQLVariable> | null
    /** Tile filters to override the ones in the query */
    tileFiltersOverride?: TileFilters | null
    /** The tab of the scene if the insight is a full scene insight */
    tabId?: string | null
}

export interface SetInsightOptions {
    /** this overrides the in-flight filters on the page, which may not equal the last returned API response */
    overrideQuery?: boolean
    /** calling with this updates the "last saved" filters */
    fromPersistentApi?: boolean
}

export enum SurveySchedule {
    Once = 'once',
    Recurring = 'recurring',
    Always = 'always',
}

export enum SurveyPartialResponses {
    Yes = 'true',
    No = 'false',
}

export interface SurveyEventsWithProperties {
    name: string
    propertyFilters?: {
        [propertyName: string]: {
            values: string[]
            operator: PropertyMatchType
        }
    }
}

export interface SurveyDisplayConditions {
    url?: string
    selector?: string
    seenSurveyWaitPeriodInDays?: number
    urlMatchType?: SurveyMatchType
    deviceTypes?: string[]
    deviceTypesMatchType?: SurveyMatchType
    linkedFlagVariant?: string
    actions: {
        values: {
            id: number
            name: string
        }[]
    } | null
    events: {
        repeatedActivation?: boolean
        values: SurveyEventsWithProperties[]
    } | null
}

export enum SurveyEventName {
    SHOWN = 'survey shown',
    DISMISSED = 'survey dismissed',
    SENT = 'survey sent',
}

export enum SurveyEventProperties {
    SURVEY_ID = '$survey_id',
    SURVEY_RESPONSE = '$survey_response',
    SURVEY_ITERATION = '$survey_iteration',
    SURVEY_PARTIALLY_COMPLETED = '$survey_partially_completed',
    SURVEY_SUBMISSION_ID = '$survey_submission_id',
    SURVEY_COMPLETED = '$survey_completed',
}

export interface SurveyEventStats {
    total_count: number
    total_count_only_seen: number
    unique_persons: number
    unique_persons_only_seen: number
    first_seen: string | null
    last_seen: string | null
}

export interface SurveyRates {
    response_rate: number
    dismissal_rate: number
    unique_users_response_rate: number
    unique_users_dismissal_rate: number
}

export interface SurveyStats {
    [SurveyEventName.SHOWN]: SurveyEventStats
    [SurveyEventName.DISMISSED]: SurveyEventStats
    [SurveyEventName.SENT]: SurveyEventStats
}
export interface SurveyStatsResponse {
    stats: SurveyStats
    rates: SurveyRates
}

export interface ChoiceQuestionResponseData {
    label: string
    value: number
    isPredefined: boolean
    // For unique responses (value === 1), include person data for display
    distinctId?: string
    personProperties?: Record<string, any>
    timestamp?: string
}

export interface OpenQuestionResponseData {
    distinctId: string
    response: string
    personProperties?: Record<string, any>
    timestamp?: string
}

export interface ChoiceQuestionProcessedResponses {
    type: SurveyQuestionType.SingleChoice | SurveyQuestionType.Rating | SurveyQuestionType.MultipleChoice
    data: ChoiceQuestionResponseData[]
    totalResponses: number
}

export interface OpenQuestionProcessedResponses {
    type: SurveyQuestionType.Open
    data: OpenQuestionResponseData[]
    totalResponses: number
}

export type QuestionProcessedResponses = ChoiceQuestionProcessedResponses | OpenQuestionProcessedResponses

export interface ResponsesByQuestion {
    [questionId: string]: QuestionProcessedResponses
}

export interface ConsolidatedSurveyResults {
    responsesByQuestion: {
        [questionId: string]: QuestionProcessedResponses
    }
}

/**
 * Raw survey response data from the SQL query.
 * Each SurveyResponseRow represents one user's complete response to all questions.
 *
 * Structure:
 * - response[questionIndex] contains the answer to that specific question
 * - For rating/single choice/open questions: response[questionIndex] is a string
 * - For multiple choice questions: response[questionIndex] is a string[]
 * - The last elements may contain metadata like person properties and distinct_id
 *
 * Example:
 * [
 *   ["9", ["Customer case studies"], "Great product!", "user123"],
 *   ["7", ["Tutorials", "Other"], "Good but could improve", "user456"]
 * ]
 */
export type SurveyResponseRow = Array<null | string | string[]>
export type SurveyRawResults = SurveyResponseRow[]

export interface Survey extends WithAccessControl {
    /** UUID */
    id: string
    name: string
    type: SurveyType
    description: string
    schedule?: SurveySchedule | null
    linked_flag_id: number | null
    linked_flag: FeatureFlagBasicType | null
    targeting_flag: FeatureFlagBasicType | null
    targeting_flag_filters?: FeatureFlagFilters
    conditions: SurveyDisplayConditions | null
    appearance: SurveyAppearance | null
    questions: (BasicSurveyQuestion | LinkSurveyQuestion | RatingSurveyQuestion | MultipleSurveyQuestion)[]
    created_at: string
    created_by: UserBasicType | null
    start_date: string | null
    end_date: string | null
    archived: boolean
    remove_targeting_flag?: boolean
    responses_limit: number | null
    iteration_count?: number | null
    iteration_frequency_days?: number | null
    iteration_start_dates?: string[]
    current_iteration?: number | null
    current_iteration_start_date?: string
    response_sampling_start_date?: string | null
    response_sampling_interval_type?: string | null
    response_sampling_interval?: number | null
    response_sampling_limit?: number | null
    response_sampling_daily_limits?: string[] | null
    enable_partial_responses?: boolean | null
    _create_in_folder?: string | null
}

export enum SurveyMatchType {
    Exact = PropertyOperator.Exact,
    IsNot = PropertyOperator.IsNot,
    Contains = PropertyOperator.IContains,
    NotIContains = PropertyOperator.NotIContains,
    Regex = PropertyOperator.Regex,
    NotRegex = PropertyOperator.NotRegex,
}

export enum SurveyType {
    Popover = 'popover',
    Widget = 'widget', // feedback button survey
    FullScreen = 'full_screen',
    API = 'api',
    ExternalSurvey = 'external_survey',
}

export enum SurveyPosition {
    TopLeft = 'top_left',
    TopCenter = 'top_center',
    TopRight = 'top_right',
    MiddleLeft = 'middle_left',
    MiddleCenter = 'middle_center',
    MiddleRight = 'middle_right',
    Left = 'left',
    Center = 'center',
    Right = 'right',
    NextToTrigger = 'next_to_trigger',
}

export enum SurveyWidgetType {
    Button = 'button',
    Tab = 'tab',
    Selector = 'selector',
}

export type SurveyQuestionDescriptionContentType = 'html' | 'text'

export interface SurveyAppearance {
    backgroundColor?: string
    submitButtonColor?: string
    // TODO: remove submitButtonText in favor of buttonText once it's more deprecated
    submitButtonText?: string
    submitButtonTextColor?: string
    ratingButtonColor?: string
    ratingButtonActiveColor?: string
    borderColor?: string
    placeholder?: string
    whiteLabel?: boolean
    displayThankYouMessage?: boolean
    thankYouMessageHeader?: string
    thankYouMessageDescription?: string
    thankYouMessageDescriptionContentType?: SurveyQuestionDescriptionContentType
    thankYouMessageCloseButtonText?: string
    autoDisappear?: boolean
    position?: SurveyPosition
    zIndex?: string
    shuffleQuestions?: boolean
    surveyPopupDelaySeconds?: number
    // widget only
    widgetType?: SurveyWidgetType
    widgetSelector?: string
    widgetLabel?: string
    widgetColor?: string
    fontFamily?: (typeof WEB_SAFE_FONTS)[number]['value']
    disabledButtonOpacity?: string
    maxWidth?: string
    textSubtleColor?: string
    inputBackground?: string
    boxPadding?: string
    boxShadow?: string
    borderRadius?: string
}

export interface SurveyQuestionBase {
    question: string
    id?: string
    description?: string | null
    descriptionContentType?: SurveyQuestionDescriptionContentType
    optional?: boolean
    buttonText?: string
    branching?:
        | NextQuestionBranching
        | ConfirmationMessageBranching
        | ResponseBasedBranching
        | SpecificQuestionBranching
}

export interface BasicSurveyQuestion extends SurveyQuestionBase {
    type: SurveyQuestionType.Open
}

export interface LinkSurveyQuestion extends SurveyQuestionBase {
    type: SurveyQuestionType.Link
    link: string | null
}

export interface RatingSurveyQuestion extends SurveyQuestionBase {
    type: SurveyQuestionType.Rating
    display: 'number' | 'emoji'
    scale: SurveyRatingScaleValue
    lowerBoundLabel: string
    upperBoundLabel: string
    skipSubmitButton?: boolean
    branching?:
        | NextQuestionBranching
        | ConfirmationMessageBranching
        | ResponseBasedBranching
        | SpecificQuestionBranching
}

export interface MultipleSurveyQuestion extends SurveyQuestionBase {
    type: SurveyQuestionType.SingleChoice | SurveyQuestionType.MultipleChoice
    choices: string[]
    shuffleOptions?: boolean
    hasOpenChoice?: boolean
    skipSubmitButton?: boolean
    branching?:
        | NextQuestionBranching
        | ConfirmationMessageBranching
        | ResponseBasedBranching
        | SpecificQuestionBranching
}

export type SurveyQuestion = BasicSurveyQuestion | LinkSurveyQuestion | RatingSurveyQuestion | MultipleSurveyQuestion

export enum SurveyQuestionType {
    Open = 'open',
    MultipleChoice = 'multiple_choice',
    SingleChoice = 'single_choice',
    Rating = 'rating',
    Link = 'link',
}

export enum SurveyQuestionBranchingType {
    NextQuestion = 'next_question',
    End = 'end',
    ResponseBased = 'response_based',
    SpecificQuestion = 'specific_question',
}

interface NextQuestionBranching {
    type: SurveyQuestionBranchingType.NextQuestion
}

interface ConfirmationMessageBranching {
    type: SurveyQuestionBranchingType.End
}

interface ResponseBasedBranching {
    type: SurveyQuestionBranchingType.ResponseBased
    responseValues: Record<string, any>
}

interface SpecificQuestionBranching {
    type: SurveyQuestionBranchingType.SpecificQuestion
    index: number
}

export interface FeatureFlagGroupType {
    properties?: AnyPropertyFilter[]
    rollout_percentage?: number | null
    variant?: string | null
    users_affected?: number
    sort_key?: string | null // Client-side only stable id for sorting.
    description?: string | null
}

export interface MultivariateFlagVariant {
    key: string
    name?: string | null
    rollout_percentage: number
}

export interface MultivariateFlagOptions {
    variants: MultivariateFlagVariant[]
}

export enum FeatureFlagEvaluationRuntime {
    SERVER = 'server',
    CLIENT = 'client',
    ALL = 'all',
}

export interface FeatureFlagFilters {
    groups: FeatureFlagGroupType[]
    multivariate?: MultivariateFlagOptions | null
    aggregation_group_type_index?: integer | null
    payloads?: Record<string, JsonType>
    super_groups?: FeatureFlagGroupType[]
}

export interface FeatureFlagBasicType {
    id: number
    team_id: TeamType['id']
    key: string
    /* The description field (the name is a misnomer because of its legacy). */
    name: string
    filters: FeatureFlagFilters
    deleted: boolean
    active: boolean
    ensure_experience_continuity: boolean | null
}

export interface FeatureFlagType extends Omit<FeatureFlagBasicType, 'id' | 'team_id'>, WithAccessControl {
    /** Null means that the flag has never been saved yet (it's new). */
    id: number | null
    created_by: UserBasicType | null
    created_at: string | null
    updated_at: string | null
    version: number | null
    last_modified_by: UserBasicType | null
    is_simple_flag: boolean
    rollout_percentage: number | null
    experiment_set: number[] | null
    features: EarlyAccessFeatureType[] | null
    surveys: Survey[] | null
    rollback_conditions: FeatureFlagRollbackConditions[]
    performed_rollback: boolean
    can_edit: boolean
    tags: string[]
    evaluation_tags: string[]
    usage_dashboard?: number
    analytics_dashboards?: number[] | null
    has_enriched_analytics?: boolean
    is_remote_configuration: boolean
    has_encrypted_payloads: boolean
    status: 'ACTIVE' | 'INACTIVE' | 'STALE' | 'DELETED' | 'UNKNOWN'
    _create_in_folder?: string | null
    evaluation_runtime: FeatureFlagEvaluationRuntime
    _should_create_usage_dashboard?: boolean
    last_called_at?: string | null
}

export interface OrganizationFeatureFlag {
    flag_id: number | null
    team_id: number | null
    created_by: UserBasicType | null
    created_at: string | null
    is_simple_flag: boolean
    rollout_percentage: number | null
    filters: FeatureFlagFilters
    active: boolean
}

export interface OrganizationFeatureFlagsCopyBody {
    feature_flag_key: FeatureFlagType['key']
    from_project: TeamType['id']
    target_project_ids: TeamType['id'][]
}

export type OrganizationFeatureFlags = {
    flag_id: FeatureFlagType['id']
    team_id: TeamType['id']
    active: FeatureFlagType['active']
}[]

export interface FeatureFlagRollbackConditions {
    threshold: number
    threshold_type: string
    threshold_metric?: FilterType
    operator?: string
}

export enum FeatureFlagStatus {
    ACTIVE = 'active',
    INACTIVE = 'inactive',
    STALE = 'stale',
    DELETED = 'deleted',
    UNKNOWN = 'unknown',
}

export interface FeatureFlagStatusResponse {
    status: FeatureFlagStatus
    reason: string
}

export interface CombinedFeatureFlagAndValueType {
    feature_flag: FeatureFlagType
    value: boolean | string
}

export interface Feature {
    id: number | null
    name: string
}

export enum EarlyAccessFeatureStage {
    Draft = 'draft',
    Concept = 'concept',
    Alpha = 'alpha',
    Beta = 'beta',
    GeneralAvailability = 'general-availability',
    Archived = 'archived',
}

export enum EarlyAccessFeatureTabs {
    OptedIn = 'opted-in',
    OptedOut = 'opted-out',
}

export interface EarlyAccessFeatureType {
    /** UUID */
    id: string
    feature_flag: FeatureFlagBasicType
    name: string
    description: string
    stage: EarlyAccessFeatureStage
    /** Documentation URL. Can be empty. */
    documentation_url: string
    created_at: string
    _create_in_folder?: string | null
}

export interface NewEarlyAccessFeatureType extends Omit<EarlyAccessFeatureType, 'id' | 'created_at' | 'feature_flag'> {
    feature_flag_id: number | undefined
}

export interface UserBlastRadiusType {
    users_affected: number
    total_users: number
}

export enum ScheduledChangeModels {
    FeatureFlag = 'FeatureFlag',
}

export enum ScheduledChangeOperationType {
    UpdateStatus = 'update_status',
    AddReleaseCondition = 'add_release_condition',
    UpdateVariants = 'update_variants',
}

export type ScheduledChangePayload =
    | { operation: ScheduledChangeOperationType.UpdateStatus; value: boolean }
    | { operation: ScheduledChangeOperationType.AddReleaseCondition; value: FeatureFlagFilters }
    | {
          operation: ScheduledChangeOperationType.UpdateVariants
          value: { variants: MultivariateFlagVariant[]; payloads?: Record<string, any> }
      }

export interface ScheduledChangeType {
    id: number
    team_id: number
    record_id: number | string
    model_name: ScheduledChangeModels
    payload: ScheduledChangePayload
    scheduled_at: string
    executed_at: string | null
    failure_reason: string | null
    created_at: string | null
    created_by: UserBasicType
}

export interface PrevalidatedInvite {
    id: string
    target_email: string
    first_name: string
    organization_name: string
}

interface InstancePreferencesInterface {
    /** Whether debug queries option should be shown on the command palette. */
    debug_queries: boolean
    /** Whether paid features showcasing / upsells are completely disabled throughout the app. */
    disable_paid_fs: boolean
}

export interface PreflightStatus {
    // Attributes that accept undefined values (i.e. `?`) are not received when unauthenticated
    django: boolean
    plugins: boolean
    redis: boolean
    db: boolean
    clickhouse: boolean
    kafka: boolean
    /** An initiated instance is one that already has any organization(s). */
    initiated: boolean
    /** Org creation is allowed on Cloud OR initiated self-hosted organizations with a license and MULTI_ORG_ENABLED. */
    can_create_org: boolean
    /** Whether this is PostHog Cloud. */
    cloud: boolean
    /** Whether this is a managed demo environment. */
    demo: boolean
    celery: boolean
    realm: Realm
    region: Region | null
    available_social_auth_providers: AuthBackends
    available_timezones?: Record<string, number>
    opt_out_capture?: boolean
    email_service_available: boolean
    slack_service: {
        available: boolean
        client_id?: string
    }
    data_warehouse_integrations: {
        hubspot: {
            client_id?: string
        }
        salesforce: {
            client_id?: string
        }
    }
    /** Whether PostHog is running in settings.DEBUG or settings.E2E_TESTING. */
    is_debug?: boolean
    /** Whether PostHog is running with settings.TEST. */
    is_test?: boolean
    licensed_users_available?: number | null
    openai_available?: boolean
    site_url?: string
    instance_preferences?: InstancePreferencesInterface
    buffer_conversion_seconds?: number
    object_storage: boolean
    public_egress_ip_addresses?: string[]
    dev_disable_navigation_hooks?: boolean
}

// TODO: Consolidate this and DashboardMode
export enum ItemMode {
    Edit = 'edit',
    View = 'view',
    Subscriptions = 'subscriptions',
    Sharing = 'sharing',
    Alerts = 'alerts',
}

export enum DashboardPlacement {
    Dashboard = 'dashboard', // When on the standard dashboard page
    CustomerAnalytics = 'customer-analytics', // When embedded on the customer analytics page
    ProjectHomepage = 'project-homepage', // When embedded on the project homepage
    FeatureFlag = 'feature-flag',
    Public = 'public', // When viewing the dashboard publicly
    Export = 'export', // When the dashboard is being exported (alike to being printed)
    Person = 'person', // When the dashboard is being viewed on a person page
    Group = 'group', // When the dashboard is being viewed on a group page
    Builtin = 'builtin', // Dashboard built into product UI with external controls provided by parent context
}

// Default mode is null
export enum DashboardMode {
    Edit = 'edit', // When the dashboard is being edited
    Fullscreen = 'fullscreen', // When the dashboard is on full screen (presentation) mode
    Sharing = 'sharing', // When the sharing configuration is opened
}

// Hotkeys for local (component) actions
export type HotKey =
    | 'a'
    | 'b'
    | 'c'
    | 'd'
    | 'e'
    | 'f'
    | 'h'
    | 'i'
    | 'j'
    | 'k'
    | 'l'
    | 'm'
    | 'n'
    | 'o'
    | 'p'
    | 'q'
    | 'r'
    | 's'
    | 't'
    | 'u'
    | 'v'
    | 'w'
    | 'x'
    | 'y'
    | 'z'
    | 'escape'
    | 'enter'
    | 'space'
    | 'tab'
    | 'arrowleft'
    | 'arrowright'
    | 'arrowdown'
    | 'arrowup'
    | 'forwardslash'

export type HotKeyOrModifier = HotKey | 'shift' | 'option' | 'command'

export interface EventDefinition {
    id: string
    name: string
    description?: string
    tags?: string[]
    owner?: UserBasicType | null
    created_at?: string
    last_seen_at?: string
    last_updated_at?: string // alias for last_seen_at to achieve event and action parity
    updated_at?: string
    updated_by?: UserBasicType | null
    verified?: boolean
    verified_at?: string
    verified_by?: string
    is_action?: boolean
    hidden?: boolean
    default_columns?: string[]
}

export interface EventDefinitionMetrics {
    query_usage_30_day: number
}

// TODO duplicated from plugin server. Follow-up to de-duplicate
export enum PropertyType {
    DateTime = 'DateTime',
    String = 'String',
    Numeric = 'Numeric',
    Boolean = 'Boolean',
    Duration = 'Duration',
    Selector = 'Selector',
    Cohort = 'Cohort',
    Assignee = 'Assignee',
    StringArray = 'StringArray',
    Flag = 'Flag',
}

export enum PropertyDefinitionType {
    Event = 'event',
    EventMetadata = 'event_metadata',
    RevenueAnalytics = 'revenue_analytics',
    Person = 'person',
    Group = 'group',
    Session = 'session',
    LogEntry = 'log_entry',
    Meta = 'meta',
    Resource = 'resource',
    Log = 'log',
    FlagValue = 'flag_value',
}

export interface PropertyDefinition {
    id: string
    name: string
    description?: string
    tags?: string[]
    updated_at?: string
    updated_by?: UserBasicType | null
    is_numerical?: boolean // Marked as optional to allow merge of EventDefinition & PropertyDefinition
    is_seen_on_filtered_events?: boolean // Indicates whether this property has been seen for a particular set of events (when `eventNames` query string is sent); calculated at query time, not stored in the db
    property_type?: PropertyType
    type?: PropertyDefinitionType
    created_at?: string // TODO: Implement
    last_seen_at?: string // TODO: Implement
    example?: string
    is_action?: boolean
    verified?: boolean
    verified_at?: string
    verified_by?: string
    hidden?: boolean
    virtual?: boolean
}

export enum PropertyDefinitionState {
    Pending = 'pending',
    Loading = 'loading',
    Missing = 'missing',
    Error = 'error',
}

export type PropertyDefinitionVerificationStatus = 'verified' | 'hidden' | 'visible'
export type Definition = EventDefinition | PropertyDefinition

export interface PersonProperty {
    id: number
    name: string
    count: number
}

export type GroupTypeIndex = 0 | 1 | 2 | 3 | 4

export interface GroupType {
    group_type: string
    group_type_index: GroupTypeIndex
    name_singular?: string | null
    name_plural?: string | null
    detail_dashboard?: number | null
    default_columns?: string[]
}

export type GroupTypeProperties = Record<number, Array<PersonProperty>>

export interface Group {
    created_at: string
    group_key: string
    group_type_index: GroupTypeIndex
    group_properties: Record<string, any>
    notebook: string | null
}

export interface UserInterviewType {
    id: string
    created_by: UserBasicType
    created_at: string
    transcript: string
    summary: string
    interviewee_emails: string[]
}

export enum ExperimentConclusion {
    Won = 'won',
    Lost = 'lost',
    Inconclusive = 'inconclusive',
    StoppedEarly = 'stopped_early',
    Invalid = 'invalid',
}

export interface ExperimentHoldoutType {
    id: number | null
    name: string
    description: string | null
    filters: FeatureFlagGroupType[]
    created_by: UserBasicType | null
    created_at: string | null
    updated_at: string | null
}

export enum ExperimentStatsMethod {
    Bayesian = 'bayesian',
    Frequentist = 'frequentist',
}

export interface Experiment {
    id: ExperimentIdType
    name: string
    type?: string
    description?: string
    feature_flag_key: string
    feature_flag?: FeatureFlagBasicType
    exposure_cohort?: number
    exposure_criteria?: ExperimentExposureCriteria
    filters: TrendsFilterType | FunnelsFilterType
    metrics: (ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
    metrics_secondary: (ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
    primary_metrics_ordered_uuids: string[] | null
    secondary_metrics_ordered_uuids: string[] | null
    saved_metrics_ids: { id: number; metadata: { type: 'primary' | 'secondary' } }[]
    saved_metrics: any[]
    parameters: {
        /**
         * This is the state of the Running Time Calculator modal, while
         * minimum_detectable_effect, recommended_running_time, and recommended_sample_size
         * are the results of the Running Time Calculator.
         */
        exposure_estimate_config?: {
            eventFilter: EventConfig | null
            metric: ExperimentMetric | null
            conversionRateInputType: ConversionRateInputType
            manualConversionRate: number | null
            uniqueUsers: number | null
        } | null
        minimum_detectable_effect?: number
        recommended_running_time?: number
        recommended_sample_size?: number
        feature_flag_variants: MultivariateFlagVariant[]
        custom_exposure_filter?: FilterType
        aggregation_group_type_index?: integer
        variant_screenshot_media_ids?: Record<string, string[]>
    }
    start_date?: string | null
    end_date?: string | null
    archived?: boolean
    secondary_metrics: SecondaryExperimentMetric[]
    created_at: string | null
    created_by: UserBasicType | null
    updated_at: string | null
    holdout_id?: number | null
    holdout?: ExperimentHoldoutType
    stats_config?: {
        version?: number
        method?: ExperimentStatsMethod
        timeseries?: boolean
    }
    _create_in_folder?: string | null
    conclusion?: ExperimentConclusion | null
    conclusion_comment?: string | null
    user_access_level: AccessControlLevel
}

export interface FunnelExperimentVariant {
    key: string
    success_count: number
    failure_count: number
}

export interface TrendExperimentVariant {
    key: string
    count: number
    exposure: number
    absolute_exposure: number
}

export interface SecondaryExperimentMetric {
    name: string
    filters: Partial<FilterType>
}

export interface SelectOption {
    value: string
    label?: string
}

export enum FilterLogicalOperator {
    And = 'AND',
    Or = 'OR',
}

export interface PropertyGroupFilter {
    type: FilterLogicalOperator
    values: PropertyGroupFilterValue[]
}

export interface PropertyGroupFilterValue {
    type: FilterLogicalOperator
    values: (AnyPropertyFilter | PropertyGroupFilterValue)[]
}

export interface CohortCriteriaGroupFilter {
    id?: string
    type: FilterLogicalOperator
    values: AnyCohortCriteriaType[] | CohortCriteriaGroupFilter[]
    sort_key?: string // Client-side only stable id for sorting.
}

export interface SelectOptionWithChildren extends SelectOption {
    children: React.ReactChildren
    ['data-attr']: string
    key: string
}

export interface CoreFilterDefinition {
    label: string
    description?: string | ReactNode
    examples?: (string | number | boolean)[]
    /** System properties are hidden in properties table by default. */
    system?: boolean
    type?: PropertyType
    /** Virtual properties are not "sent as", because they are calculated from other properties or SQL expressions **/
    virtual?: boolean
    /** whether this is a property PostHog adds to aid with debugging */
    used_for_debug?: boolean
}

export interface TileParams {
    title: string
    targetPath: string
    openInNewTab?: boolean
    hoverText?: string
    icon: JSX.Element
    class?: string
}

export interface TiledIconModuleProps {
    tiles: TileParams[]
    header?: string
    subHeader?: string
    analyticsModuleKey?: string
}

export type EventOrPropType = EventDefinition & PropertyDefinition

export interface AppContext {
    current_user: UserType | null
    current_project: ProjectType | null
    current_team: TeamType | TeamPublicType | null
    preflight: PreflightStatus
    default_event_name: string
    persisted_feature_flags?: string[]
    anonymous: boolean
    frontend_apps?: Record<number, FrontendAppConfig>
    effective_resource_access_control: Record<AccessControlResourceType, AccessControlLevel>
    resource_access_control: Record<AccessControlResourceType, AccessControlLevel>
    commit_sha?: string
    /** Whether the user was autoswitched to the current item's team. */
    switched_team: TeamType['id'] | null
    /** Support flow aid: a staff-only list of users who may be impersonated to access this resource. */
    suggested_users_with_access?: UserBasicType[]
    livestream_host?: string
}

export type StoredMetricMathOperations = 'max' | 'min' | 'sum'

export interface PathEdgeParameters {
    edgeLimit?: number | undefined
    minEdgeWeight?: number | undefined
    maxEdgeWeight?: number | undefined
}

export enum SignificanceCode {
    Significant = 'significant',
    NotEnoughExposure = 'not_enough_exposure',
    LowWinProbability = 'low_win_probability',
    HighLoss = 'high_loss',
    HighPValue = 'high_p_value',
}

export enum HelpType {
    Slack = 'slack',
    GitHub = 'github',
    Email = 'email',
    Docs = 'docs',
    Updates = 'updates',
    SupportForm = 'support_form',
}

export interface DateMappingOption {
    key: string
    inactive?: boolean // Options removed due to low usage (see relevant PR); will not show up for new insights but will be kept for existing
    values: string[]
    getFormattedDate?: (date: dayjs.Dayjs, format?: string) => string
    defaultInterval?: IntervalType
}

interface BreadcrumbBase {
    /** E.g. scene, tab, or scene with item ID. Particularly important for `onRename`. */
    key: string | number | [scene: Scene | string, key: string | number]
    /** Whether to show a custom popover */
    popover?: Pick<PopoverProps, 'overlay' | 'matchWidth'>
    /** Whether to show a custom popover for the project */
    isPopoverProject?: boolean
    iconType?: FileSystemIconType | 'blank' | 'loading'
}
export interface LinkBreadcrumb extends BreadcrumbBase {
    /** Name to display. */
    name: string | JSX.Element | null | undefined
    symbol?: never
    /** Path to link to. */
    path?: string
    /** Extra tag shown next to name. */
    tag?: string | null
    onRename?: never
}
export interface RenamableBreadcrumb extends BreadcrumbBase {
    /** Name to display. */
    name: string | JSX.Element | null | undefined
    symbol?: never
    path?: never
    /** When this is set, an "Edit" button shows up next to the title */
    onRename?: (newName: string) => Promise<void>
    /** When this is true, the name is always in edit mode, and `onRename` runs on every input change. */
    forceEditMode?: boolean
}
export interface SymbolBreadcrumb extends BreadcrumbBase {
    name?: never
    /** Symbol, e.g. a lettermark or a profile picture. */
    symbol: React.ReactElement
    path?: never
}
export interface ProjectTreeBreadcrumb extends BreadcrumbBase {
    /** Last part of path */
    name: string
    /** Rest of the path. */
    path?: string
    type: string
    ref?: string
    symbol?: never
    onRename?: never
}
export type Breadcrumb = LinkBreadcrumb | RenamableBreadcrumb | SymbolBreadcrumb | ProjectTreeBreadcrumb

export enum GraphType {
    Bar = 'bar',
    HorizontalBar = 'horizontalBar',
    Line = 'line',
    Histogram = 'histogram',
    Pie = 'doughnut',
}

export type GraphDataset = ChartDataset<ChartType> &
    Partial<
        Pick<
            TrendResult,
            | 'count'
            | 'label'
            | 'days'
            | 'labels'
            | 'data'
            | 'compare'
            | 'compare_label'
            | 'status'
            | 'action'
            | 'actions'
            | 'breakdown_value'
            | 'persons_urls'
            | 'persons'
            | 'filter'
        >
    > & {
        /** Used in filtering out visibility of datasets. Set internally by chart.js */
        id: number
        /** Toggled on to draw incompleteness lines in LineGraph.tsx */
        dotted?: boolean
        /** Array of breakdown values used only in ActionsHorizontalBar/ActionsPie.tsx data */
        breakdownValues?: (string | number | string[] | undefined)[]
        /** Array of breakdown labels used only in ActionsHorizontalBar/ActionsPie.tsx data */
        breakdownLabels?: (string | number | undefined)[]
        /** Array of compare labels used only in ActionsHorizontalBar/ActionsPie.tsx data */
        compareLabels?: (CompareLabelType | undefined | null)[]
        /** Array of persons used only in (ActionsHorizontalBar|ActionsPie).tsx */
        personsValues?: (Person | undefined | null)[]
        index?: number
        /** Value (count) for specific data point; only valid in the context of an xy intercept */
        pointValue?: number
        /** Value (count) for specific data point; only valid in the context of an xy intercept */
        personUrl?: string
        /** Action/event filter defition */
        action?: ActionFilter | null
        yAxisID?: string
    }

export type GraphPoint = InteractionItem & { dataset: GraphDataset }

interface PointsPayload {
    pointsIntersectingLine: GraphPoint[]
    pointsIntersectingClick: GraphPoint[]
    clickedPointNotLine: boolean
    referencePoint: GraphPoint
}

export interface GraphPointPayload {
    points: PointsPayload
    index: number
    value?: number
    /** Contains the dataset for all the points in the same x-axis point; allows switching between matching points in the x-axis */
    crossDataset?: GraphDataset[]
    /** ID for the currently selected series */
    seriesId?: number
}

export enum CompareLabelType {
    Current = 'current',
    Previous = 'previous',
}

export interface InstanceSetting {
    key: string
    value: boolean | string | number | null
    value_type: 'bool' | 'str' | 'int'
    description?: string
    editable: boolean
    is_secret: boolean
}

export enum FunnelMathType {
    AnyMatch = 'total',
    FirstTimeForUser = 'first_time_for_user',
    FirstTimeForUserWithFilters = 'first_time_for_user_with_filters',
}

export enum BaseMathType {
    TotalCount = 'total',
    UniqueUsers = 'dau',
    WeeklyActiveUsers = 'weekly_active',
    MonthlyActiveUsers = 'monthly_active',
    UniqueSessions = 'unique_session',
    FirstTimeForUser = 'first_time_for_user',
    FirstMatchingEventForUser = 'first_matching_event_for_user',
}

export enum CalendarHeatmapMathType {
    TotalCount = 'total',
    UniqueUsers = 'dau',
}

export enum PropertyMathType {
    Average = 'avg',
    Sum = 'sum',
    Minimum = 'min',
    Maximum = 'max',
    Median = 'median',
    P75 = 'p75',
    P90 = 'p90',
    P95 = 'p95',
    P99 = 'p99',
}

export enum CountPerActorMathType {
    Average = 'avg_count_per_actor',
    Minimum = 'min_count_per_actor',
    Maximum = 'max_count_per_actor',
    Median = 'median_count_per_actor',
    P75 = 'p75_count_per_actor',
    P90 = 'p90_count_per_actor',
    P95 = 'p95_count_per_actor',
    P99 = 'p99_count_per_actor',
}

export enum HogQLMathType {
    HogQL = 'hogql',
}
export enum GroupMathType {
    UniqueGroup = 'unique_group',
}

export enum ExperimentMetricMathType {
    TotalCount = 'total',
    Sum = 'sum',
    UniqueSessions = 'unique_session',
    Min = 'min',
    Max = 'max',
    Avg = 'avg',
    UniqueUsers = 'dau',
    UniqueGroup = 'unique_group',
    HogQL = 'hogql',
}

export enum ExperimentMetricGoal {
    Increase = 'increase',
    Decrease = 'decrease',
}

export enum ActorGroupType {
    Person = 'person',
    GroupPrefix = 'group',
}

export enum BehavioralEventType {
    PerformEvent = 'performed_event',
    PerformMultipleEvents = 'performed_event_multiple',
    PerformSequenceEvents = 'performed_event_sequence',
    NotPerformedEvent = 'not_performed_event',
    NotPerformSequenceEvents = 'not_performed_event_sequence',
    HaveProperty = 'have_property',
    NotHaveProperty = 'not_have_property',
}

export enum BehavioralCohortType {
    InCohort = 'in_cohort',
    NotInCohort = 'not_in_cohort',
}

export enum BehavioralLifecycleType {
    PerformEventFirstTime = 'performed_event_first_time',
    PerformEventRegularly = 'performed_event_regularly',
    StopPerformEvent = 'stopped_performing_event',
    StartPerformEventAgain = 'restarted_performing_event',
}

export enum TimeUnitType {
    Day = 'day',
    Week = 'week',
    Month = 'month',
    Year = 'year',
}

export enum DateOperatorType {
    BeforeTheLast = 'before_the_last',
    Between = 'between',
    NotBetween = 'not_between',
    OnTheDate = 'on_the_date',
    NotOnTheDate = 'not_on_the_date',
    Since = 'since',
    Before = 'before',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
}

export enum SingleFieldDateType {
    IsDateExact = 'is_date_exact',
    IsDateBefore = 'is_date_before',
    IsDateAfter = 'is_date_after',
}

export enum ValueOptionType {
    MostRecent = 'most_recent',
    Previous = 'previous',
    OnDate = 'on_date',
}

export type WeekdayType = 'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday'

export interface SubscriptionType {
    id: number
    insight?: number
    dashboard?: number
    target_type: string
    target_value: string
    frequency: 'daily' | 'weekly' | 'monthly' | 'yearly'
    interval: number
    byweekday: WeekdayType[] | null
    bysetpos: number | null
    start_date: string
    until_date?: string
    title: string
    summary: string
    created_by?: UserBasicType | null
    created_at: string
    updated_at: string
    deleted?: boolean
}

export type SmallTimeUnit = 'hours' | 'minutes' | 'seconds'

export type Duration = {
    timeValue: number
    unit: SmallTimeUnit
}

export enum EventDefinitionType {
    Event = 'event',
    EventInternal = 'event_internal',
    EventCustom = 'event_custom',
    EventPostHog = 'event_posthog',
}

export const INTEGRATION_KINDS = [
    'slack',
    'salesforce',
    'hubspot',
    'google-pubsub',
    'google-cloud-storage',
    'google-ads',
    'google-sheets',
    'linkedin-ads',
    'snapchat',
    'intercom',
    'email',
    'twilio',
    'linear',
    'github',
    'gitlab',
    'meta-ads',
    'clickup',
    'reddit-ads',
    'databricks',
    'tiktok-ads',
] as const

export type IntegrationKind = (typeof INTEGRATION_KINDS)[number]

export interface IntegrationType {
    id: number
    kind: IntegrationKind
    display_name: string
    icon_url: string
    config: any
    created_by?: UserBasicType | null
    created_at: string
    errors?: string
}

export interface EmailIntegrationDomainGroupedType {
    domain: string
    integrations: IntegrationType[]
}

export interface SlackChannelType {
    id: string
    name: string
    is_private: boolean
    is_ext_shared: boolean
    is_member: boolean
    is_private_without_access?: boolean
}

export interface TwilioPhoneNumberType {
    sid: string
    phone_number: string
    friendly_name: string
}
export interface LinearTeamType {
    id: string
    name: string
}

export interface SharePasswordType {
    id: string
    created_at: string
    note: string
    created_by_email: string
    is_active: boolean
    password?: string
}

export interface SharingConfigurationType {
    enabled: boolean
    access_token: string
    created_at: string
    password_required: boolean
    settings?: SharingConfigurationSettings
    share_passwords?: SharePasswordType[]
}

export enum ExporterFormat {
    PNG = 'image/png',
    CSV = 'text/csv',
    PDF = 'application/pdf',
    JSON = 'application/json',
    XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    WEBM = 'video/webm',
    MP4 = 'video/mp4',
    GIF = 'image/gif',
}

/** Exporting directly from the browser to a file */
export type LocalExportContext = {
    localData: string
    filename: string
    mediaType?: ExporterFormat
}

export type OnlineExportContext = {
    method?: string
    path: string
    query?: any
    body?: any
    filename?: string
}

export type QueryExportContext = {
    source: Record<string, any>
    filename?: string
}

export interface ReplayExportContext {
    session_recording_id: string
    timestamp?: number
    css_selector?: string
    width?: number
    height?: number
    filename?: string
    duration?: number
    mode?: SessionRecordingPlayerMode
}

export interface HeatmapExportContext {
    heatmap_url: string
    heatmap_data_url?: string
    heatmap_type?: HeatmapType
    filename?: string
    heatmap_filters?: HeatmapFilters
    heatmap_color_palette?: string | null
    heatmap_fixed_position_mode?: HeatmapFixedPositionMode
    common_filters?: CommonFilters
}

export type ExportContext =
    | OnlineExportContext
    | LocalExportContext
    | QueryExportContext
    | ReplayExportContext
    | HeatmapExportContext

export interface ExportedAssetType {
    id: number
    export_format: ExporterFormat
    dashboard?: number
    insight?: number
    export_context?: ExportContext
    has_content: boolean
    filename: string
    created_at: string
    expires_after?: string
    exception?: string
}

export enum FeatureFlagReleaseType {
    ReleaseToggle = 'Release toggle',
    Variants = 'Multiple variants',
}

export interface MediaUploadResponse {
    id: string
    image_location: string
    name: string
}

export enum RolloutConditionType {
    Insight = 'insight',
    Sentry = 'sentry',
}

export enum Resource {
    FEATURE_FLAGS = 'feature flags',
}

export interface RoleType {
    id: string
    name: string
    members: RoleMemberType[]
    created_at: string
    created_by: UserBasicType | null
}

export interface RoleMemberType {
    id: string
    user: UserBaseType
    role_id: string
    joined_at: string
    updated_at: string
    user_uuid: string
}

export type APIScopeObject =
    | 'action'
    | 'access_control'
    | 'activity_log'
    | 'annotation'
    | 'batch_export'
    | 'cohort'
    | 'dashboard'
    | 'dashboard_template'
    | 'dataset'
    | 'desktop_recording'
    | 'early_access_feature'
    | 'endpoint'
    | 'error_tracking'
    | 'evaluation'
    | 'event_definition'
    | 'experiment'
    | 'export'
    | 'feature_flag'
    | 'group'
    | 'hog_function'
    | 'insight'
    | 'integration'
    | 'live_debugger'
    | 'notebook'
    | 'organization'
    | 'organization_member'
    | 'person'
    | 'plugin'
    | 'project'
    | 'property_definition'
    | 'query'
    | 'revenue_analytics'
    | 'session_recording'
    | 'session_recording_playlist'
    | 'sharing_configuration'
    | 'subscription'
    | 'survey'
    | 'task'
    | 'user'
    | 'warehouse_table'
    | 'warehouse_view'
    | 'web_analytics'
    | 'webhook'

export type APIScopeAction = 'read' | 'write'

export type APIScope = {
    key: APIScopeObject
    objectPlural: string
    info?: string | JSX.Element
    disabledActions?: APIScopeAction[]
    disabledWhenProjectScoped?: boolean
    description?: string
    warnings?: Partial<Record<APIScopeAction, string | JSX.Element>>
}

export type APIScopePreset = { value: string; label: string; scopes: string[]; isCloudOnly?: boolean }

export enum AccessControlLevel {
    None = 'none',
    Member = 'member',
    Admin = 'admin',
    Viewer = 'viewer',
    Editor = 'editor',
    Manager = 'manager',
}

export interface AccessControlTypeBase {
    created_by: UserBasicType | null
    created_at: string
    updated_at: string
    resource: APIScopeObject
    access_level: AccessControlLevel | null
    organization_member?: OrganizationMemberType['id'] | null
    role?: RoleType['id'] | null
}

export interface AccessControlTypeProject extends AccessControlTypeBase {}

export interface AccessControlTypeMember extends AccessControlTypeBase {
    organization_member: OrganizationMemberType['id']
}

export interface AccessControlTypeOrganizationAdmins extends AccessControlTypeBase {
    organization_admin_members: OrganizationMemberType['id'][]
}

export interface AccessControlTypeRole extends AccessControlTypeBase {
    role: RoleType['id']
}

export type AccessControlType = AccessControlTypeProject | AccessControlTypeMember | AccessControlTypeRole

export type AccessControlUpdateType = Pick<AccessControlType, 'access_level' | 'organization_member' | 'role'> & {
    resource?: AccessControlType['resource']
}

export type AccessControlResponseType = {
    access_controls: AccessControlType[]
    available_access_levels: AccessControlLevel[]
    user_access_level: AccessControlLevel
    default_access_level: AccessControlLevel
    minimum_access_level?: AccessControlLevel
    user_can_edit_access_levels: boolean
}

export type JsonType = string | number | boolean | null | { [key: string]: JsonType } | Array<JsonType>

export type PromptButtonType = 'primary' | 'secondary'
export type PromptType = 'modal' | 'popup'

export type PromptPayload = {
    title: string
    body: string
    type: PromptType
    image?: string
    url_match?: string
    primaryButtonText?: string
    secondaryButtonText?: string
    primaryButtonURL?: string
}

export type PromptFlag = {
    flag: string
    payload: PromptPayload
    showingPrompt: boolean
    locationCSS?: Partial<CSSStyleDeclaration>
    tooltipCSS?: Partial<CSSStyleDeclaration>
}

// Should be kept in sync with "posthog/models/activity_logging/activity_log.py"
export enum ActivityScope {
    ACTION = 'Action',
    ALERT_CONFIGURATION = 'AlertConfiguration',
    ANNOTATION = 'Annotation',
    BATCH_EXPORT = 'BatchExport',
    BATCH_IMPORT = 'BatchImport',
    FEATURE_FLAG = 'FeatureFlag',
    PERSON = 'Person',
    PERSONAL_API_KEY = 'PersonalAPIKey',
    GROUP = 'Group',
    INSIGHT = 'Insight',
    PLUGIN = 'Plugin',
    PLUGIN_CONFIG = 'PluginConfig',
    HOG_FUNCTION = 'HogFunction',
    HOG_FLOW = 'HogFlow',
    DATA_MANAGEMENT = 'DataManagement',
    EVENT_DEFINITION = 'EventDefinition',
    PROPERTY_DEFINITION = 'PropertyDefinition',
    NOTEBOOK = 'Notebook',
    DASHBOARD = 'Dashboard',
    REPLAY = 'Replay',
    // TODO: doh! we don't need replay and recording
    RECORDING = 'recording',
    EXPERIMENT = 'Experiment',
    SURVEY = 'Survey',
    EARLY_ACCESS_FEATURE = 'EarlyAccessFeature',
    COMMENT = 'Comment',
    COHORT = 'Cohort',
    TEAM = 'Team',
    ORGANIZATION = 'Organization',
    ORGANIZATION_MEMBERSHIP = 'OrganizationMembership',
    ORGANIZATION_INVITE = 'OrganizationInvite',
    ERROR_TRACKING_ISSUE = 'ErrorTrackingIssue',
    DATA_WAREHOUSE_SAVED_QUERY = 'DataWarehouseSavedQuery',
    USER_INTERVIEW = 'UserInterview',
    TAG = 'Tag',
    TAGGED_ITEM = 'TaggedItem',
    EXTERNAL_DATA_SOURCE = 'ExternalDataSource',
    EXTERNAL_DATA_SCHEMA = 'ExternalDataSchema',
    ENDPOINT = 'Endpoint',
    HEATMAP = 'Heatmap',
    USER = 'User',
}

export type CommentType = {
    id: string
    content: string | null
    rich_content: JSONContent | null
    version: number
    created_at: string
    created_by: UserBasicType | null
    source_comment?: string | null
    scope: ActivityScope | string
    item_id?: string
    item_context: Record<string, any> | null
    /** only on the type to support patching for soft delete */
    deleted?: boolean
}

export type CommentCreationParams = { mentions?: number[]; slug?: string }

export interface DataWarehouseCredential {
    access_key: string
    access_secret: string
}
export interface DataWarehouseTable {
    /** UUID */
    id: string
    name: string
    format: DataWarehouseTableTypes
    url_pattern: string
    credential: DataWarehouseCredential
    external_data_source?: ExternalDataSource
    external_schema?: SimpleExternalDataSourceSchema
}

export type DataWarehouseTableTypes = 'CSV' | 'Parquet' | 'JSON' | 'CSVWithNames'

export interface DataWarehouseSavedQuery {
    /** UUID */
    id: string
    name: string
    query: HogQLQuery
    columns: DatabaseSchemaField[]
    last_run_at?: string
    sync_frequency?: string
    status?: string
    managed_viewset_kind: DataWarehouseManagedViewsetKind | null
    latest_error: string | null
    latest_history_id?: string
    is_materialized?: boolean
}

export interface DataWarehouseSavedQueryDraft {
    id: string
    query: HogQLQuery
    saved_query_id?: string
    created_at: string
    updated_at: string
    name: string
    edited_history_id?: string
}

export interface DataWarehouseViewLinkConfiguration {
    experiments_optimized?: boolean
    experiments_timestamp_key?: string | null
}

export interface DataWarehouseViewLink {
    id: string
    source_table_name?: string
    source_table_key?: string
    joining_table_name?: string
    joining_table_key?: string
    field_name?: string
    created_by?: UserBasicType | null
    created_at?: string | null
    configuration?: DataWarehouseViewLinkConfiguration
}

export interface DataWarehouseViewLinkValidation {
    is_valid: boolean
    msg: string | null
    hogql: string | null
    results: any[]
}

export interface QueryTabState {
    id: string
    state: Record<string, any>
}

export enum DataWarehouseSettingsTab {
    Managed = 'managed',
    SelfManaged = 'self-managed',
}

export const manualLinkSources = ['aws', 'google-cloud', 'cloudflare-r2', 'azure'] as const

export type ManualLinkSourceType = (typeof manualLinkSources)[number]

export interface ExternalDataSourceRevenueAnalyticsConfig {
    enabled: boolean
    include_invoiceless_charges: boolean
}

export interface ExternalDataSourceCreatePayload {
    source_type: ExternalDataSourceType
    prefix: string
    payload: Record<string, any>
}
export interface ExternalDataSource {
    id: string
    source_id: string
    connection_id: string
    status: string
    source_type: ExternalDataSourceType
    prefix: string
    latest_error: string | null
    last_run_at?: Dayjs
    schemas: ExternalDataSourceSchema[]
    sync_frequency: DataWarehouseSyncInterval
    job_inputs: Record<string, any>
    revenue_analytics_config: ExternalDataSourceRevenueAnalyticsConfig
}

export interface DataModelingJob {
    id: string
    saved_query_id: string
    status: 'Running' | 'Completed' | 'Failed' | 'Cancelled'
    rows_materialized: number
    rows_expected: number | null
    error: string | null
    created_at: string
    last_run_at: string
    workflow_id: string
    workflow_run_id: string
}

export interface SimpleExternalDataSourceSchema {
    id: string
    name: string
    should_sync: boolean
    last_synced_at?: Dayjs
}

export type SchemaIncrementalFieldsResponse = {
    incremental_fields: IncrementalField[]
    incremental_available: boolean
    append_available: boolean
    full_refresh_available: boolean
}

// numeric is snowflake specific and objectid is mongodb specific
export type IncrementalFieldType = 'integer' | 'numeric' | 'datetime' | 'date' | 'timestamp' | 'objectid'

export interface IncrementalField {
    label: string // the field name shown in the UI
    type: IncrementalFieldType // the field type shown in the UI
    field: string // the actual database field name
    field_type: IncrementalFieldType // the actual database field type
}

export interface ExternalDataSourceSyncSchema {
    table: string
    rows?: number | null
    should_sync: boolean
    sync_time_of_day: string | null
    incremental_field: string | null
    incremental_field_type: string | null
    sync_type: 'full_refresh' | 'incremental' | 'append' | null
    incremental_fields: IncrementalField[]
    incremental_available: boolean
    append_available: boolean
}

export interface ExternalDataSourceSchema extends SimpleExternalDataSourceSchema {
    table?: SimpleDataWarehouseTable
    incremental: boolean
    sync_type: 'incremental' | 'full_refresh' | 'append' | null
    sync_time_of_day: string | null
    status?: ExternalDataSchemaStatus
    latest_error: string | null
    incremental_field: string | null
    incremental_field_type: string | null
    sync_frequency: DataWarehouseSyncInterval
}

export enum ExternalDataSchemaStatus {
    Running = 'Running',
    Completed = 'Completed',
    Failed = 'Failed',
    Paused = 'Paused',
    Cancelled = 'Cancelled',
}

export enum ExternalDataJobStatus {
    Running = 'Running',
    Completed = 'Completed',
    Failed = 'Failed',
    BillingLimits = 'Billing limits',
    BillingLimitTooLow = 'Billing limit too low',
}

export interface ExternalDataJob {
    id: string
    created_at: string
    finished_at: string
    status: ExternalDataJobStatus
    schema: SimpleExternalDataSourceSchema
    rows_synced: number
    latest_error: string
    workflow_run_id?: string
}

export interface SimpleDataWarehouseTable {
    id: string
    name: string
    columns: DatabaseSchemaField[]
    row_count: number
}

export type BatchExportServiceS3 = {
    type: 'S3'
    config: {
        bucket_name: string
        region: string
        prefix: string
        aws_access_key_id: string
        aws_secret_access_key: string
        exclude_events: string[]
        include_events: string[]
        compression: string | null
        encryption: string | null
        kms_key_id: string | null
        endpoint_url: string | null
        file_format: string
        max_file_size_mb: number | null
        use_virtual_style_addressing: boolean
    }
}

export type BatchExportServicePostgres = {
    type: 'Postgres'
    config: {
        user: string
        password: string
        host: string
        port: number
        database: string
        schema: string
        table_name: string
        has_self_signed_cert: boolean
        exclude_events: string[]
        include_events: string[]
    }
}

export type BatchExportServiceSnowflake = {
    type: 'Snowflake'
    config: {
        account: string
        database: string
        warehouse: string
        user: string
        authentication_type: 'password' | 'keypair'
        password: string | null
        private_key: string | null
        private_key_passphrase: string | null
        schema: string
        table_name: string
        role: string | null
        exclude_events: string[]
        include_events: string[]
    }
}

export type BatchExportServiceBigQuery = {
    type: 'BigQuery'
    config: {
        project_id: string
        private_key: string
        private_key_id: string
        client_email: string
        token_uri: string
        dataset_id: string
        table_id: string
        exclude_events: string[]
        include_events: string[]
        use_json_type: boolean
    }
}

export type BatchExportServiceHTTP = {
    type: 'HTTP'
    config: {
        url: string
        token: string
        exclude_events: string[]
        include_events: string[]
    }
}

export type BatchExportServiceRedshift = {
    type: 'Redshift'
    config: {
        user: string
        password: string
        host: string
        port: number
        database: string
        schema: string
        table_name: string
        properties_data_type: boolean
        mode: 'COPY' | 'INSERT'
        authorization_mode: 'IAMRole' | 'Credentials'
        copy_inputs: BatchExportServiceRedshiftCopyInputs | null
        exclude_events: string[]
        include_events: string[]
    }
}

export type BatchExportServiceRedshiftCopyInputs = {
    s3_bucket: string
    s3_key_prefix: string
    region_name: string
    bucket_credentials: AWSCredentials
    authorization: string | AWSCredentials
}

export type AWSCredentials = {
    aws_access_key_id: string
    aws_secret_access_key: string
}

export type BatchExportServiceDatabricks = {
    type: 'Databricks'
    integration: number
    config: {
        http_path: string
        catalog: string
        schema: string
        table_name: string
        use_variant_type: boolean
        exclude_events: string[]
        include_events: string[]
    }
}

// When adding a new option here also add a icon for it to
// frontend/public/services/
// and update RenderBatchExportIcon
export const BATCH_EXPORT_SERVICE_NAMES: BatchExportService['type'][] = [
    'S3',
    'Snowflake',
    'Postgres',
    'BigQuery',
    'Redshift',
    'HTTP',
    'Databricks',
]
export type BatchExportService =
    | BatchExportServiceS3
    | BatchExportServiceSnowflake
    | BatchExportServicePostgres
    | BatchExportServiceBigQuery
    | BatchExportServiceRedshift
    | BatchExportServiceHTTP
    | BatchExportServiceDatabricks

export type PipelineInterval = 'hour' | 'day' | 'every 5 minutes'

export type DataWarehouseSyncInterval = '5min' | '30min' | '1hour' | '6hour' | '12hour' | '24hour' | '7day' | '30day'
export type OrNever = 'never'

export type BatchExportConfiguration = {
    // User provided data for the export. This is the data that the user
    // provides when creating the export.
    id: string
    team_id: number
    name: string
    destination: BatchExportService
    interval: PipelineInterval
    created_at: string
    start_at: string | null
    end_at: string | null
    paused: boolean
    model: string
    filters: AnyPropertyFilter[]
    latest_runs?: BatchExportRun[]
}

export type BatchExportConfigurationTestStepStatus = 'Passed' | 'Failed'

export type BatchExportConfigurationTestStepResult = {
    status: BatchExportConfigurationTestStepStatus
    message: string
}

export type BatchExportConfigurationTestStep = {
    name: string
    description: string
    result: BatchExportConfigurationTestStepResult | null
}

export type BatchExportConfigurationTest = {
    steps: BatchExportConfigurationTestStep[]
}

export type RawBatchExportRun = {
    id: string
    status:
        | 'Cancelled'
        | 'Completed'
        | 'ContinuedAsNew'
        | 'Failed'
        | 'FailedRetryable'
        | 'Terminated'
        | 'TimedOut'
        | 'Running'
        | 'Starting'
    created_at: string
    data_interval_start?: string
    data_interval_end: string
    last_updated_at?: string
}

export type BatchExportRun = {
    id: string
    status:
        | 'Cancelled'
        | 'Completed'
        | 'ContinuedAsNew'
        | 'Failed'
        | 'FailedRetryable'
        | 'Terminated'
        | 'TimedOut'
        | 'Running'
        | 'Starting'
    created_at: Dayjs
    data_interval_start?: Dayjs
    data_interval_end: Dayjs
    last_updated_at?: Dayjs
}

export type GroupedBatchExportRuns = {
    last_run_at: Dayjs
    data_interval_start: Dayjs
    data_interval_end: Dayjs
    runs: BatchExportRun[]
}

export type BatchExportBackfillProgress = {
    total_runs?: number
    finished_runs?: number
    progress?: number
}

export type RawBatchExportBackfill = {
    id: string
    status:
        | 'Cancelled'
        | 'Completed'
        | 'ContinuedAsNew'
        | 'Failed'
        | 'FailedRetryable'
        | 'Terminated'
        | 'TimedOut'
        | 'Running'
        | 'Starting'
    created_at: string
    finished_at?: string
    start_at?: string
    end_at?: string
    last_updated_at?: string
    progress?: BatchExportBackfillProgress
}

export type BatchExportBackfill = {
    id: string
    status:
        | 'Cancelled'
        | 'Completed'
        | 'ContinuedAsNew'
        | 'Failed'
        | 'FailedRetryable'
        | 'Terminated'
        | 'TimedOut'
        | 'Running'
        | 'Starting'
    created_at?: Dayjs
    finished_at?: Dayjs
    start_at?: Dayjs
    end_at?: Dayjs
    last_updated_at?: Dayjs
    progress?: BatchExportBackfillProgress
}

export type SDK = {
    name: string
    key: string
    recommended?: boolean
    tags: SDKTag[]
    image:
        | string
        | JSX.Element
        // storybook handles require() differently, so we need to support both
        | {
              default: string
          }
    docsLink: string
}

export enum SDKKey {
    ANDROID = 'android',
    ANGULAR = 'angular',
    ANTHROPIC = 'anthropic',
    ASTRO = 'astro',
    API = 'api',
    BUBBLE = 'bubble',
    DJANGO = 'django',
    DOCUSAURUS = 'docusaurus',
    DOTNET = 'dotnet',
    ELIXIR = 'elixir',
    FRAMER = 'framer',
    FLUTTER = 'flutter',
    GATSBY = 'gatsby',
    GO = 'go',
    GOOGLE_GEMINI = 'google_gemini',
    GOOGLE_TAG_MANAGER = 'google_tag_manager',
    HELICONE = 'helicone',
    HTML_SNIPPET = 'html',
    IOS = 'ios',
    JAVA = 'java',
    JS_WEB = 'javascript_web',
    LARAVEL = 'laravel',
    LANGCHAIN = 'langchain',
    LANGFUSE = 'langfuse',
    LITELLM = 'litellm',
    MANUAL_CAPTURE = 'manual_capture',
    NEXT_JS = 'nextjs',
    NODE_JS = 'nodejs',
    NUXT_JS = 'nuxtjs',
    OPENAI = 'openai',
    OPENROUTER = 'openrouter',
    PHP = 'php',
    PYTHON = 'python',
    REACT = 'react',
    REACT_NATIVE = 'react_native',
    REMIX = 'remix',
    RETOOL = 'retool',
    RUBY = 'ruby',
    RUDDERSTACK = 'rudderstack',
    RUST = 'rust',
    SEGMENT = 'segment',
    SENTRY = 'sentry',
    SHOPIFY = 'shopify',
    SVELTE = 'svelte',
    TRACELOOP = 'traceloop',
    VERCEL_AI = 'vercel_ai',
    VUE_JS = 'vuejs',
    WEBFLOW = 'webflow',
    WORDPRESS = 'wordpress',
}

export enum SDKTag {
    POPULAR = 'Most popular',
    WEB = 'Web',
    MOBILE = 'Mobile',
    SERVER = 'Server',
    LLM = 'LLM',
    INTEGRATION = 'Integration',
    OTHER = 'Other',
}

export type SDKInstructionsMap = Partial<Record<SDKKey, ReactNode>>

export interface AppMetricsUrlParams {
    tab?: AppMetricsTab
    from?: string
    error?: [string, string]
}

export enum AppMetricsTab {
    Logs = 'logs',
    ProcessEvent = 'processEvent',
    OnEvent = 'onEvent',
    ComposeWebhook = 'composeWebhook',
    ExportEvents = 'exportEvents',
    ScheduledTask = 'scheduledTask',
    HistoricalExports = 'historical_exports',
    History = 'history',
}

export enum SidePanelTab {
    Max = 'max',
    Notebooks = 'notebook',
    Support = 'support',
    Docs = 'docs',
    Activation = 'activation',
    Settings = 'settings',
    Activity = 'activity',
    Discussion = 'discussion',
    Status = 'status',
    Exports = 'exports',
    AccessControl = 'access-control',
    SdkDoctor = 'sdk-doctor',
}

export interface ProductPricingTierSubrows {
    columns: LemonTableColumns<BillingTableTierAddonRow>
    rows: BillingTableTierAddonRow[]
}

export type BillingTableTierAddonRow = {
    productName: string
    price: string
    usage: string
    total: string
    projectedTotal: string
    icon?: string
}

export type BillingTableTierRow = {
    volume: string
    basePrice: string
    usage: string
    total: string
    projectedTotal: string | ReactNode
    subrows: ProductPricingTierSubrows
}

export type BillingInvoiceItemRow = {
    description: string
    dateRange?: string
    amount: string
    isBold?: boolean
}

export type AvailableOnboardingProducts = Record<
    | ProductKey.PRODUCT_ANALYTICS
    | ProductKey.SESSION_REPLAY
    | ProductKey.FEATURE_FLAGS
    | ProductKey.EXPERIMENTS
    | ProductKey.SURVEYS
    | ProductKey.DATA_WAREHOUSE
    | ProductKey.WEB_ANALYTICS
    | ProductKey.ERROR_TRACKING
    | ProductKey.LLM_ANALYTICS,
    OnboardingProduct
>

export type OnboardingProduct = {
    name: string
    breadcrumbsName?: string
    description?: string
    icon: string
    iconColor: string
    url: string
    scene: Scene
}

export type CyclotronJobInputSchemaType = {
    type:
        | 'string'
        | 'number'
        | 'boolean'
        | 'dictionary'
        | 'choice'
        | 'json'
        | 'integration'
        | 'integration_field'
        | 'email'
        | 'native_email'
    key: string
    label: string
    choices?: { value: string; label: string }[]
    required?: boolean
    default?: any
    secret?: boolean
    hidden?: boolean
    templating?: boolean
    description?: string
    integration?: string
    integration_key?: string
    integration_field?: string
    requires_field?: string
    requiredScopes?: string
}

export type CyclotronJobMasking = {
    ttl: number | null
    threshold?: number | null
    hash: string
    bytecode?: any
}

// subset of EntityFilter
export interface CyclotronJobFilterBase {
    id: string
    name?: string | null
    order?: number
    properties?: (EventPropertyFilter | PersonPropertyFilter | ElementPropertyFilter)[]
}

export interface CyclotronJobFilterEvents extends CyclotronJobFilterBase {
    type: 'events'
}

export interface CyclotronJobFilterActions extends CyclotronJobFilterBase {
    type: 'actions'
}

export type CyclotronJobFilterPropertyFilter =
    | EventPropertyFilter
    | PersonPropertyFilter
    | ElementPropertyFilter
    | GroupPropertyFilter
    | FeaturePropertyFilter
    | HogQLPropertyFilter
    | FlagPropertyFilter

export interface CyclotronJobFiltersType {
    source?: 'events' | 'person-updates'
    events?: CyclotronJobFilterEvents[]
    actions?: CyclotronJobFilterActions[]
    properties?: CyclotronJobFilterPropertyFilter[]
    filter_test_accounts?: boolean
    bytecode?: any[]
    bytecode_error?: string
}

export type CyclotronJobInputType = CyclotronInputType

export interface HogFunctionMappingType {
    name: string
    disabled?: boolean
    inputs_schema?: CyclotronJobInputSchemaType[]
    inputs?: Record<string, CyclotronInputType> | null
    filters?: CyclotronJobFiltersType | null
}
export interface HogFunctionMappingTemplateType extends HogFunctionMappingType {
    name: string
    include_by_default?: boolean
}

export type HogFunctionTypeType =
    | 'destination'
    | 'internal_destination'
    | 'source'
    | 'source_webhook'
    | 'site_destination'
    | 'site_app'
    | 'transformation'

export type HogFunctionType = {
    id: string
    type: HogFunctionTypeType
    icon_url?: string
    icon_class_name?: string // allow for overriding css styling on the icon case by case
    name: string
    description: string
    created_by: UserBasicType | null
    created_at: string
    updated_at: string
    enabled: boolean
    hog: string
    execution_order?: number
    inputs_schema?: CyclotronJobInputSchemaType[]
    inputs?: Record<string, CyclotronInputType> | null
    mappings?: HogFunctionMappingType[] | null
    masking?: CyclotronJobMasking | null
    filters?: CyclotronJobFiltersType | null
    template?: HogFunctionTemplateType
    status?: HogFunctionStatus
}

export type HogFunctionTemplateStatus = 'stable' | 'alpha' | 'beta' | 'deprecated' | 'coming_soon' | 'hidden'

// Contexts change the way the UI is rendered allowing different teams to customize the UI for their use case
export type HogFunctionConfigurationContextId = 'standard' | 'error-tracking' | 'activity-log' | 'insight-alerts'

export type HogFunctionSubTemplateIdType =
    | 'early-access-feature-enrollment'
    | 'survey-response'
    | 'activity-log'
    | 'error-tracking-issue-created'
    | 'error-tracking-issue-reopened'
    | 'insight-alert-firing'

export type HogFunctionConfigurationType = Omit<
    HogFunctionType,
    'id' | 'created_at' | 'created_by' | 'updated_at' | 'status' | 'hog'
> & {
    hog?: HogFunctionType['hog'] // In the config it can be empty if using a template
    _create_in_folder?: string | null
}
export type HogFlowConfigurationType = Omit<HogFlow, 'id' | 'created_at' | 'created_by' | 'updated_at' | 'status'>
export type CyclotronJobConfigurationType = HogFunctionConfigurationType | HogFlowConfigurationType

export type HogFunctionSubTemplateType = Pick<
    HogFunctionType,
    'filters' | 'inputs' | 'masking' | 'mappings' | 'type'
> & {
    template_id: HogFunctionTemplateType['id']
    context_id: HogFunctionConfigurationContextId
    sub_template_id: HogFunctionSubTemplateIdType
    name?: string
    description?: string
}

export type HogFunctionTemplateType = Pick<
    HogFunctionType,
    'id' | 'type' | 'name' | 'inputs_schema' | 'filters' | 'icon_url' | 'icon_class_name' | 'masking' | 'mappings'
> & {
    status: HogFunctionTemplateStatus
    free: boolean
    mapping_templates?: HogFunctionMappingTemplateType[]
    description?: string | JSX.Element
    code: string
    code_language: 'javascript' | 'hog'
    /** Whether the template should be conditionally rendered based on a feature flag */
    flag?: string
}

export type HogFunctionTemplateWithSubTemplateType = HogFunctionTemplateType & {
    sub_template_id?: HogFunctionSubTemplateIdType
}

export type HogFunctionIconResponse = {
    id: string
    name: string
    url: string
}

export enum HogWatcherState {
    healthy = 1,
    overflowed = 2,
    disabled = 3,
    forcefully_degraded = 11,
    forcefully_disabled = 12,
}

export type HogFunctionStatus = {
    state: HogWatcherState
    tokens: number
}

export type CyclotronJobInvocationGlobals = {
    project: {
        id: number
        name: string
        url: string
    }
    source?: {
        name: string
        url: string
    }
    event: {
        uuid: string
        event: string
        elements_chain: string
        distinct_id: string
        properties: Record<string, any>
        timestamp: string
        url: string
    }
    person?: {
        id: string
        properties: Record<string, any>
        name: string
        url: string
    }
    groups?: Record<
        string,
        {
            id: string // the "key" of the group
            type: string
            index: number
            url: string
            properties: Record<string, any>
        }
    >
    // Only applies to sources
    request?: {
        body: Record<string, any>
        headers: Record<string, string>
        ip?: string
    }
    // For HogFlows, workflow-level variables
    variables?: Record<string, any>
}

export type CyclotronJobInvocationGlobalsWithInputs = Partial<CyclotronJobInvocationGlobals> & {
    inputs?: Record<string, any>
}

export type CyclotronJobTestInvocationResult = {
    status: 'success' | 'error' | 'skipped'
    logs: LogEntry[]
    result: any
    errors?: string[]
}

export type AppMetricsV2Response = {
    labels: string[]
    series: {
        name: string
        values: number[]
    }[]
}

export type AppMetricsTotalsV2Response = {
    totals: Record<string, number>
}

export type AppMetricsV2RequestParams = {
    after?: string
    before?: string
    // Comma separated list of log levels
    name?: string
    kind?: string
    interval?: 'hour' | 'day' | 'week'
    breakdown_by?: 'name' | 'kind'
}

export type SessionReplayUrlTriggerConfig = {
    url: string
    matching: 'regex'
}

export type ReplayTemplateType = {
    key: string
    name: string
    description: string
    variables?: ReplayTemplateVariableType[]
    categories: ReplayTemplateCategory[]
    icon?: ReactNode
    order?: RecordingOrder
}
export type ReplayTemplateCategory = 'B2B' | 'B2C' | 'More'

export type ReplayTemplateVariableType = {
    type: 'event' | 'flag' | 'pageview' | 'person-property' | 'snapshot_source'
    name: string
    key: string
    touched?: boolean
    value?: string
    description?: string
    filterGroup?: UniversalFiltersGroupValue
    noTouch?: boolean
}

export type GoogleAdsConversionActionType = {
    id: string
    name: string
    resourceName: string
}

export type LinkedInAdsConversionRuleType = {
    id: number
    name: string
}

export type LinkedInAdsAccountType = {
    id: number
    name: string
    campaigns: string
}

export type DataColorThemeModel = {
    id: number
    name: string
    colors: string[]
    is_global: boolean
}

export type DataColorThemeModelPayload = Omit<DataColorThemeModel, 'id' | 'is_global'> & {
    id?: number
    is_global?: boolean
}

export enum CookielessServerHashMode {
    Disabled = 0,
    Stateless = 1,
    Stateful = 2,
}

/**
 * Assistant Conversation
 */
export enum ConversationStatus {
    Idle = 'idle',
    InProgress = 'in_progress',
    Canceling = 'canceling',
}

export enum ConversationType {
    Assistant = 'assistant',
    ToolCall = 'tool_call',
    DeepResearch = 'deep_research',
}

export enum Category {
    DEEP_RESEARCH = 'deep_research',
}

export enum DeepResearchType {
    PLANNING = 'planning',
    REPORT = 'report',
}

interface _NotebookBase {
    notebook_id: string
    title: string
}

export interface DeepResearchNotebook extends _NotebookBase {
    category: Category.DEEP_RESEARCH
    notebook_type?: DeepResearchType
}

export type NotebookInfo = DeepResearchNotebook

export interface Conversation {
    id: string
    status: ConversationStatus
    title: string | null
    created_at: string | null
    updated_at: string | null
    type: ConversationType
    has_unsupported_content?: boolean
}

export interface ConversationDetail extends Conversation {
    messages: RootAssistantMessage[]
}

export enum UserRole {
    Engineering = 'engineering',
    Data = 'data',
    Product = 'product',
    Founder = 'founder',
    Leadership = 'leadership',
    Marketing = 'marketing',
    Sales = 'sales',
    Other = 'other',
}

export interface CoreMemory {
    id: string
    text: string
}

export type FileSystemIconColor = [string] | [string, string]

export interface FileSystemType {
    href?: (ref: string) => string
    // Visual name of the product
    name: string
    // Flag to determine if the product is enabled
    flag?: string
    // Used to filter the tree items by product
    filterKey?: string
    // Icon type of the icon
    iconType?: FileSystemIconType
    // Color of the icon
    iconColor?: FileSystemIconColor
}

export interface ProductManifest {
    name: string
    scenes?: Record<string, SceneConfig>
    routes?: Record<string, [string /** Scene */, string /** Scene Key (unique for layout tabs) */]>
    redirects?: Record<string, string | ((params: Params, searchParams: Params, hashParams: Params) => string)>
    urls?: Record<string, string | ((...args: any[]) => string)>
    fileSystemTypes?: Record<string, FileSystemType>
    treeItemsNew?: FileSystemImport[]
    treeItemsProducts?: FileSystemImport[]
    treeItemsGames?: FileSystemImport[]
    treeItemsMetadata?: FileSystemImport[]
}

export interface ProjectTreeRef {
    /**
     * Type of file system object.
     * Use "/" as a separator to add an internal type, e.g. "hog/site_destination".
     * Search with "hog/" to match all internal types.
     */
    type: string
    /**
     * The ref of the file system object.
     * Usually the "id" or "short_id" of the database object.
     * "null" opens the "new" page
     */
    ref: string | null
}

export type OAuthApplicationPublicMetadata = {
    name: string
    client_id: string
}
export interface EmailSenderDomainStatus {
    status: 'pending' | 'success'
    dnsRecords: (
        | {
              type: 'dkim'
              recordType: 'TXT'
              recordHostname: string
              recordValue: string
              status: 'pending' | 'success'
          }
        | {
              type: 'spf'
              recordType: 'TXT'
              recordHostname: '@'
              recordValue: string
              status: 'pending' | 'success'
          }
    )[]
}

// Representation of a `Link` model in our backend
export type LinkType = {
    id: string
    redirect_url: string
    short_link_domain: string
    short_code: string
    description?: string
    created_by: UserBasicType
    created_at: string
    updated_at: string
    _create_in_folder?: string | null
}

export interface LineageNode {
    id: string
    name: string
    type: 'view' | 'table'
    sync_frequency?: DataWarehouseSyncInterval
    last_run_at?: string
    status?: string
}

export interface LineageEdge {
    source: string
    target: string
}

export interface LineageGraph {
    nodes: LineageNode[]
    edges: LineageEdge[]
}

export interface DataWarehouseSourceRowCount {
    breakdown_of_rows_by_source: Record<string, number>
    billing_available: boolean
    billing_interval: string
    billing_period_end: string
    billing_period_start: string
    materialized_rows_in_billing_period: number
    total_rows: number
    tracked_billing_rows: number
    pending_billing_rows: number
}

export interface DataWarehouseActivityRecord {
    id: string
    type: string
    name: string | null
    status: ExternalDataJobStatus
    rows: number
    created_at: string
    finished_at: string | null
    latest_error: string | null
    workflow_run_id?: string
}

export type HeatmapType = 'screenshot' | 'iframe' | 'recording'
export type HeatmapStatus = 'processing' | 'completed' | 'failed'

export interface HeatmapScreenshotType {
    id: number
    name: string
    short_id: string
    url: string
    data_url: string | null
    type: HeatmapType
    width: number
    status: HeatmapStatus
    has_content: boolean
    created_at: string
    updated_at: string
    exception?: string
    error?: string // Added for error responses from content endpoint
    created_by?: UserBasicType | null
}

export type HeatmapScreenshotContentResponse =
    | { success: true; data: Response } // 200: PNG image data
    | { success: false; data: HeatmapScreenshotType } // 202/404/501: JSON with screenshot metadata

export interface HeatmapSavedFilters {
    order: string
    search: string
    createdBy: number | 'All users'
    page: number
    limit: number
    offset: number
}

export interface DataWarehouseDashboardDataSource {
    id: string
    name: string
    status: string | null
    lastSync: string | null
    rowCount: number | null
    url: string
}

export interface DataWarehouseJobStatsRequestPayload {
    days: 1 | 7 | 30
}

export interface DataWarehouseJobStats {
    days: number
    cutoff_time: string
    total_jobs: number
    successful_jobs: number
    failed_jobs: number
    external_data_jobs: {
        total: number
        running: number
        successful: number
        failed: number
    }
    modeling_jobs: {
        total: number
        running: number
        successful: number
        failed: number
    }
    breakdown: Record<
        string,
        {
            successful: number
            failed: number
        }
    >
}

export enum OnboardingStepKey {
    INSTALL = 'install',
    LINK_DATA = 'link_data',
    PLANS = 'plans',
    VERIFY = 'verify',
    PRODUCT_CONFIGURATION = 'configure',
    REVERSE_PROXY = 'proxy',
    INVITE_TEAMMATES = 'invite_teammates',
    DASHBOARD_TEMPLATE = 'dashboard_template',
    DASHBOARD_TEMPLATE_CONFIGURE = 'dashboard_template_configure',
    SESSION_REPLAY = 'session_replay',
    AUTHORIZED_DOMAINS = 'authorized_domains',
    SOURCE_MAPS = 'source_maps',
    ALERTS = 'alerts',
}

export interface Dataset {
    id: string
    name: string
    description: string | null
    metadata: Record<string, any> | null
    team: number
    created_at: string
    updated_at: string
    created_by: UserBasicType
    deleted: boolean
}

export interface DatasetItem {
    id: string
    dataset: string
    team: number
    input: Record<string, any> | null
    output: Record<string, any> | null
    metadata: Record<string, any> | null
    ref_trace_id: string | null
    ref_timestamp: string | null
    ref_source_id: string | null
    created_by: UserBasicType
    updated_at: string
    created_at: string
    deleted: boolean
}

// Managed viewset
export interface DataWarehouseManagedViewsetSavedQuery {
    id: string
    created_at: string
    created_by_id: string | null
    name: string
}

// Session Summaries
export interface SessionSummaryResponse {
    patterns: EnrichedSessionGroupSummaryPattern[]
}

export interface EnrichedSessionGroupSummaryPattern {
    pattern_id: number
    pattern_name: string
    pattern_description: string
    severity: 'low' | 'medium' | 'high' | 'critical'
    indicators: string[]
    events: PatternAssignedEventSegmentContext[]
    stats: EnrichedSessionGroupSummaryPatternStats
}

export interface EnrichedSessionGroupSummaryPatternStats {
    occurences: number
    sessions_affected: number
    sessions_affected_ratio: number
    segments_success_ratio: number
}

export interface PatternAssignedEventSegmentContext {
    segment_name: string
    segment_outcome: string
    segment_success: boolean
    segment_index: number
    previous_events_in_segment: EnrichedPatternAssignedEvent[]
    target_event: EnrichedPatternAssignedEvent
    next_events_in_segment: EnrichedPatternAssignedEvent[]
}

export interface EnrichedPatternAssignedEvent {
    event_id: string
    event_uuid: string
    session_id: string
    description: string
    abandonment: boolean
    confusion: boolean
    exception: string | null
    timestamp: string
    milliseconds_since_start: number
    window_id: string | null
    current_url: string | null
    event: string
    event_type: string | null
    event_index: number
}
