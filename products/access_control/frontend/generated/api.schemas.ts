/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `object` - object
 * * `parent_object` - parent_object
 * * `resource` - resource
 * * `parent_resource` - parent_resource
 * * `system_default` - system_default
 * * `org_admin` - org_admin
 * * `creator` - creator
 * * `org_membership` - org_membership
 */
export type ResolvedAccessSourceEnumApi = (typeof ResolvedAccessSourceEnumApi)[keyof typeof ResolvedAccessSourceEnumApi]

export const ResolvedAccessSourceEnumApi = {
    Object: 'object',
    ParentObject: 'parent_object',
    Resource: 'resource',
    ParentResource: 'parent_resource',
    SystemDefault: 'system_default',
    OrgAdmin: 'org_admin',
    Creator: 'creator',
    OrgMembership: 'org_membership',
} as const

/**
 * * `member` - member
 * * `role` - role
 * * `default` - default
 */
export type ResolvedAccessSourceSubjectEnumApi =
    (typeof ResolvedAccessSourceSubjectEnumApi)[keyof typeof ResolvedAccessSourceSubjectEnumApi]

export const ResolvedAccessSourceSubjectEnumApi = {
    Member: 'member',
    Role: 'role',
    Default: 'default',
} as const

/**
 * * `action` - action
 * * `access_control` - access_control
 * * `account` - account
 * * `activity_log` - activity_log
 * * `alert` - alert
 * * `annotation` - annotation
 * * `approvals` - approvals
 * * `autoresearch` - autoresearch
 * * `batch_export` - batch_export
 * * `batch_import` - batch_import
 * * `batch_import_support` - batch_import_support
 * * `billing` - billing
 * * `business_knowledge` - business_knowledge
 * * `canvas` - canvas
 * * `cohort` - cohort
 * * `comment` - comment
 * * `conversation` - conversation
 * * `cross_project_dashboard` - cross_project_dashboard
 * * `customer_analytics` - customer_analytics
 * * `customer_task` - customer_task
 * * `customer_journey` - customer_journey
 * * `customer_profile_config` - customer_profile_config
 * * `data_catalog` - data_catalog
 * * `data_catalog_approval` - data_catalog_approval
 * * `data_deletion` - data_deletion
 * * `dashboard` - dashboard
 * * `event_filter` - event_filter
 * * `dashboard_template` - dashboard_template
 * * `dataset` - dataset
 * * `early_access_feature` - early_access_feature
 * * `endpoint` - endpoint
 * * `engineering_analytics` - engineering_analytics
 * * `error_tracking` - error_tracking
 * * `evaluation` - evaluation
 * * `element` - element
 * * `event_definition` - event_definition
 * * `experiment` - experiment
 * * `experiment_holdout` - experiment_holdout
 * * `experiment_saved_metric` - experiment_saved_metric
 * * `export` - export
 * * `external_data_schema` - external_data_schema
 * * `external_data_source` - external_data_source
 * * `feature_flag` - feature_flag
 * * `file_system` - file_system
 * * `file_system_shortcut` - file_system_shortcut
 * * `group` - group
 * * `health_issue` - health_issue
 * * `heatmap` - heatmap
 * * `hog_flow` - hog_flow
 * * `hog_function` - hog_function
 * * `ingestion_warning` - ingestion_warning
 * * `insight` - insight
 * * `insight_variable` - insight_variable
 * * `integration` - integration
 * * `legal_document` - legal_document
 * * `link` - link
 * * `live_debugger` - live_debugger
 * * `llm_analytics` - llm_analytics
 * * `ai_observability_clusters` - ai_observability_clusters
 * * `llm_gateway` - llm_gateway
 * * `llm_playground` - llm_playground
 * * `llm_prompt` - llm_prompt
 * * `llm_provider_key` - llm_provider_key
 * * `llm_skill` - llm_skill
 * * `logs` - logs
 * * `loop` - loop
 * * `marketing_analytics` - marketing_analytics
 * * `mcp_analytics` - mcp_analytics
 * * `mcp_registry` - mcp_registry
 * * `metrics` - metrics
 * * `notebook` - notebook
 * * `offline_evaluation_ingestion` - offline_evaluation_ingestion
 * * `organization` - organization
 * * `organization_integration` - organization_integration
 * * `organization_member` - organization_member
 * * `person` - person
 * * `plugin` - plugin
 * * `product_enablement` - product_enablement
 * * `product_tour` - product_tour
 * * `project` - project
 * * `property_definition` - property_definition
 * * `query` - query
 * * `query_performance` - query_performance
 * * `replay_scanner` - replay_scanner
 * * `review_hog` - review_hog
 * * `revenue_analytics` - revenue_analytics
 * * `session_recording` - session_recording
 * * `session_recording_playlist` - session_recording_playlist
 * * `sharing_configuration` - sharing_configuration
 * * `signal_scout` - signal_scout
 * * `stamphog` - stamphog
 * * `streamlit_app` - streamlit_app
 * * `subscription` - subscription
 * * `support_ticket` - support_ticket
 * * `survey` - survey
 * * `tagger` - tagger
 * * `ticket` - ticket
 * * `task` - task
 * * `today` - today
 * * `toolbar` - toolbar
 * * `tracing` - tracing
 * * `field_note` - field_note
 * * `uploaded_media` - uploaded_media
 * * `usage_metric` - usage_metric
 * * `user` - user
 * * `user_interview` - user_interview
 * * `vision_action` - vision_action
 * * `vision_alert` - vision_alert
 * * `visual_review` - visual_review
 * * `warehouse_objects` - warehouse_objects
 * * `warehouse_table` - warehouse_table
 * * `warehouse_view` - warehouse_view
 * * `web_analytics` - web_analytics
 * * `webhook` - webhook
 * * `wizard_session` - wizard_session
 * * `wizard_run` - wizard_run
 */
export type ScopeObjectEnumApi = (typeof ScopeObjectEnumApi)[keyof typeof ScopeObjectEnumApi]

export const ScopeObjectEnumApi = {
    Action: 'action',
    AccessControl: 'access_control',
    Account: 'account',
    ActivityLog: 'activity_log',
    Alert: 'alert',
    Annotation: 'annotation',
    Approvals: 'approvals',
    Autoresearch: 'autoresearch',
    BatchExport: 'batch_export',
    BatchImport: 'batch_import',
    BatchImportSupport: 'batch_import_support',
    Billing: 'billing',
    BusinessKnowledge: 'business_knowledge',
    Canvas: 'canvas',
    Cohort: 'cohort',
    Comment: 'comment',
    Conversation: 'conversation',
    CrossProjectDashboard: 'cross_project_dashboard',
    CustomerAnalytics: 'customer_analytics',
    CustomerTask: 'customer_task',
    CustomerJourney: 'customer_journey',
    CustomerProfileConfig: 'customer_profile_config',
    DataCatalog: 'data_catalog',
    DataCatalogApproval: 'data_catalog_approval',
    DataDeletion: 'data_deletion',
    Dashboard: 'dashboard',
    EventFilter: 'event_filter',
    DashboardTemplate: 'dashboard_template',
    Dataset: 'dataset',
    EarlyAccessFeature: 'early_access_feature',
    Endpoint: 'endpoint',
    EngineeringAnalytics: 'engineering_analytics',
    ErrorTracking: 'error_tracking',
    Evaluation: 'evaluation',
    Element: 'element',
    EventDefinition: 'event_definition',
    Experiment: 'experiment',
    ExperimentHoldout: 'experiment_holdout',
    ExperimentSavedMetric: 'experiment_saved_metric',
    Export: 'export',
    ExternalDataSchema: 'external_data_schema',
    ExternalDataSource: 'external_data_source',
    FeatureFlag: 'feature_flag',
    FileSystem: 'file_system',
    FileSystemShortcut: 'file_system_shortcut',
    Group: 'group',
    HealthIssue: 'health_issue',
    Heatmap: 'heatmap',
    HogFlow: 'hog_flow',
    HogFunction: 'hog_function',
    IngestionWarning: 'ingestion_warning',
    Insight: 'insight',
    InsightVariable: 'insight_variable',
    Integration: 'integration',
    LegalDocument: 'legal_document',
    Link: 'link',
    LiveDebugger: 'live_debugger',
    LlmAnalytics: 'llm_analytics',
    AiObservabilityClusters: 'ai_observability_clusters',
    LlmGateway: 'llm_gateway',
    LlmPlayground: 'llm_playground',
    LlmPrompt: 'llm_prompt',
    LlmProviderKey: 'llm_provider_key',
    LlmSkill: 'llm_skill',
    Logs: 'logs',
    Loop: 'loop',
    MarketingAnalytics: 'marketing_analytics',
    McpAnalytics: 'mcp_analytics',
    McpRegistry: 'mcp_registry',
    Metrics: 'metrics',
    Notebook: 'notebook',
    OfflineEvaluationIngestion: 'offline_evaluation_ingestion',
    Organization: 'organization',
    OrganizationIntegration: 'organization_integration',
    OrganizationMember: 'organization_member',
    Person: 'person',
    Plugin: 'plugin',
    ProductEnablement: 'product_enablement',
    ProductTour: 'product_tour',
    Project: 'project',
    PropertyDefinition: 'property_definition',
    Query: 'query',
    QueryPerformance: 'query_performance',
    ReplayScanner: 'replay_scanner',
    ReviewHog: 'review_hog',
    RevenueAnalytics: 'revenue_analytics',
    SessionRecording: 'session_recording',
    SessionRecordingPlaylist: 'session_recording_playlist',
    SharingConfiguration: 'sharing_configuration',
    SignalScout: 'signal_scout',
    Stamphog: 'stamphog',
    StreamlitApp: 'streamlit_app',
    Subscription: 'subscription',
    SupportTicket: 'support_ticket',
    Survey: 'survey',
    Tagger: 'tagger',
    Ticket: 'ticket',
    Task: 'task',
    Today: 'today',
    Toolbar: 'toolbar',
    Tracing: 'tracing',
    FieldNote: 'field_note',
    UploadedMedia: 'uploaded_media',
    UsageMetric: 'usage_metric',
    User: 'user',
    UserInterview: 'user_interview',
    VisionAction: 'vision_action',
    VisionAlert: 'vision_alert',
    VisualReview: 'visual_review',
    WarehouseObjects: 'warehouse_objects',
    WarehouseTable: 'warehouse_table',
    WarehouseView: 'warehouse_view',
    WebAnalytics: 'web_analytics',
    Webhook: 'webhook',
    WizardSession: 'wizard_session',
    WizardRun: 'wizard_run',
} as const

/**
 * A resolved access level with the rule that supplied it — the wire form of `ResolvedAccess`.
 */
export interface ProjectAccessSourceApi {
    /** The access level that applies. */
    access_level: string
    /** How the level was derived: a rule on the object, its parent object, the resource, the parent resource, the PostHog default, an organization admin's or a creator's full access, or organization membership when the object is the organization itself.
     *
     * * `object` - object
     * * `parent_object` - parent_object
     * * `resource` - resource
     * * `parent_resource` - parent_resource
     * * `system_default` - system_default
     * * `org_admin` - org_admin
     * * `creator` - creator
     * * `org_membership` - org_membership */
    source: ResolvedAccessSourceEnumApi
    /** Whose rule decided: a member's own, a role's, or the default for everyone in the project. Null when no rule did.
     *
     * * `member` - member
     * * `role` - role
     * * `default` - default */
    source_subject: ResolvedAccessSourceSubjectEnumApi | null
    /** The resource the deciding rule belongs to.
     *
     * * `action` - action
     * * `access_control` - access_control
     * * `account` - account
     * * `activity_log` - activity_log
     * * `alert` - alert
     * * `annotation` - annotation
     * * `approvals` - approvals
     * * `autoresearch` - autoresearch
     * * `batch_export` - batch_export
     * * `batch_import` - batch_import
     * * `batch_import_support` - batch_import_support
     * * `billing` - billing
     * * `business_knowledge` - business_knowledge
     * * `canvas` - canvas
     * * `cohort` - cohort
     * * `comment` - comment
     * * `conversation` - conversation
     * * `cross_project_dashboard` - cross_project_dashboard
     * * `customer_analytics` - customer_analytics
     * * `customer_task` - customer_task
     * * `customer_journey` - customer_journey
     * * `customer_profile_config` - customer_profile_config
     * * `data_catalog` - data_catalog
     * * `data_catalog_approval` - data_catalog_approval
     * * `data_deletion` - data_deletion
     * * `dashboard` - dashboard
     * * `event_filter` - event_filter
     * * `dashboard_template` - dashboard_template
     * * `dataset` - dataset
     * * `early_access_feature` - early_access_feature
     * * `endpoint` - endpoint
     * * `engineering_analytics` - engineering_analytics
     * * `error_tracking` - error_tracking
     * * `evaluation` - evaluation
     * * `element` - element
     * * `event_definition` - event_definition
     * * `experiment` - experiment
     * * `experiment_holdout` - experiment_holdout
     * * `experiment_saved_metric` - experiment_saved_metric
     * * `export` - export
     * * `external_data_schema` - external_data_schema
     * * `external_data_source` - external_data_source
     * * `feature_flag` - feature_flag
     * * `file_system` - file_system
     * * `file_system_shortcut` - file_system_shortcut
     * * `group` - group
     * * `health_issue` - health_issue
     * * `heatmap` - heatmap
     * * `hog_flow` - hog_flow
     * * `hog_function` - hog_function
     * * `ingestion_warning` - ingestion_warning
     * * `insight` - insight
     * * `insight_variable` - insight_variable
     * * `integration` - integration
     * * `legal_document` - legal_document
     * * `link` - link
     * * `live_debugger` - live_debugger
     * * `llm_analytics` - llm_analytics
     * * `ai_observability_clusters` - ai_observability_clusters
     * * `llm_gateway` - llm_gateway
     * * `llm_playground` - llm_playground
     * * `llm_prompt` - llm_prompt
     * * `llm_provider_key` - llm_provider_key
     * * `llm_skill` - llm_skill
     * * `logs` - logs
     * * `loop` - loop
     * * `marketing_analytics` - marketing_analytics
     * * `mcp_analytics` - mcp_analytics
     * * `mcp_registry` - mcp_registry
     * * `metrics` - metrics
     * * `notebook` - notebook
     * * `offline_evaluation_ingestion` - offline_evaluation_ingestion
     * * `organization` - organization
     * * `organization_integration` - organization_integration
     * * `organization_member` - organization_member
     * * `person` - person
     * * `plugin` - plugin
     * * `product_enablement` - product_enablement
     * * `product_tour` - product_tour
     * * `project` - project
     * * `property_definition` - property_definition
     * * `query` - query
     * * `query_performance` - query_performance
     * * `replay_scanner` - replay_scanner
     * * `review_hog` - review_hog
     * * `revenue_analytics` - revenue_analytics
     * * `session_recording` - session_recording
     * * `session_recording_playlist` - session_recording_playlist
     * * `sharing_configuration` - sharing_configuration
     * * `signal_scout` - signal_scout
     * * `stamphog` - stamphog
     * * `streamlit_app` - streamlit_app
     * * `subscription` - subscription
     * * `support_ticket` - support_ticket
     * * `survey` - survey
     * * `tagger` - tagger
     * * `ticket` - ticket
     * * `task` - task
     * * `today` - today
     * * `toolbar` - toolbar
     * * `tracing` - tracing
     * * `field_note` - field_note
     * * `uploaded_media` - uploaded_media
     * * `usage_metric` - usage_metric
     * * `user` - user
     * * `user_interview` - user_interview
     * * `vision_action` - vision_action
     * * `vision_alert` - vision_alert
     * * `visual_review` - visual_review
     * * `warehouse_objects` - warehouse_objects
     * * `warehouse_table` - warehouse_table
     * * `warehouse_view` - warehouse_view
     * * `web_analytics` - web_analytics
     * * `webhook` - webhook
     * * `wizard_session` - wizard_session
     * * `wizard_run` - wizard_run */
    source_resource: ScopeObjectEnumApi
    /**
     * The deciding rule's object id, when it is an object-level rule (e.g. the source a table inherits from).
     * @nullable
     */
    source_resource_id: string | null
    /**
     * The name of the role or member whose rule decided. Null when the default or a bypass decided.
     * @nullable
     */
    subject_name: string | null
}

export interface MemberProjectAccessEntryApi {
    /** The project's id. */
    team_id: number
    /** The project's name. */
    team_name: string
    /** The member's enforced access to the project: none, member or admin. */
    access_level: string
    /** The rule that supplies the level. Read `source` and `source_subject` to tell an organization admin's bypass from a member rule, a role rule or the project default. */
    resolved: ProjectAccessSourceApi | null
    /**
     * The id of the role or organization membership whose rule decided. Null when the default or a bypass decided.
     * @nullable
     */
    subject_id: string | null
}

export interface MemberProjectAccessApi {
    /** The organization membership id. */
    organization_membership_id: string
    /** One entry per project the caller can access, including projects the member cannot. */
    projects: MemberProjectAccessEntryApi[]
}

export interface MemberProjectAccessResponseApi {
    /** One entry per visible organization member. */
    results: MemberProjectAccessApi[]
}

/**
 * A stored rule on one object, as configured for a subject.
 */
export interface AccessControlObjectRuleApi {
    /** The object's resource type, for example `dashboard`.
     *
     * * `action` - action
     * * `access_control` - access_control
     * * `account` - account
     * * `activity_log` - activity_log
     * * `alert` - alert
     * * `annotation` - annotation
     * * `approvals` - approvals
     * * `autoresearch` - autoresearch
     * * `batch_export` - batch_export
     * * `batch_import` - batch_import
     * * `batch_import_support` - batch_import_support
     * * `billing` - billing
     * * `business_knowledge` - business_knowledge
     * * `canvas` - canvas
     * * `cohort` - cohort
     * * `comment` - comment
     * * `conversation` - conversation
     * * `cross_project_dashboard` - cross_project_dashboard
     * * `customer_analytics` - customer_analytics
     * * `customer_task` - customer_task
     * * `customer_journey` - customer_journey
     * * `customer_profile_config` - customer_profile_config
     * * `data_catalog` - data_catalog
     * * `data_catalog_approval` - data_catalog_approval
     * * `data_deletion` - data_deletion
     * * `dashboard` - dashboard
     * * `event_filter` - event_filter
     * * `dashboard_template` - dashboard_template
     * * `dataset` - dataset
     * * `early_access_feature` - early_access_feature
     * * `endpoint` - endpoint
     * * `engineering_analytics` - engineering_analytics
     * * `error_tracking` - error_tracking
     * * `evaluation` - evaluation
     * * `element` - element
     * * `event_definition` - event_definition
     * * `experiment` - experiment
     * * `experiment_holdout` - experiment_holdout
     * * `experiment_saved_metric` - experiment_saved_metric
     * * `export` - export
     * * `external_data_schema` - external_data_schema
     * * `external_data_source` - external_data_source
     * * `feature_flag` - feature_flag
     * * `file_system` - file_system
     * * `file_system_shortcut` - file_system_shortcut
     * * `group` - group
     * * `health_issue` - health_issue
     * * `heatmap` - heatmap
     * * `hog_flow` - hog_flow
     * * `hog_function` - hog_function
     * * `ingestion_warning` - ingestion_warning
     * * `insight` - insight
     * * `insight_variable` - insight_variable
     * * `integration` - integration
     * * `legal_document` - legal_document
     * * `link` - link
     * * `live_debugger` - live_debugger
     * * `llm_analytics` - llm_analytics
     * * `ai_observability_clusters` - ai_observability_clusters
     * * `llm_gateway` - llm_gateway
     * * `llm_playground` - llm_playground
     * * `llm_prompt` - llm_prompt
     * * `llm_provider_key` - llm_provider_key
     * * `llm_skill` - llm_skill
     * * `logs` - logs
     * * `loop` - loop
     * * `marketing_analytics` - marketing_analytics
     * * `mcp_analytics` - mcp_analytics
     * * `mcp_registry` - mcp_registry
     * * `metrics` - metrics
     * * `notebook` - notebook
     * * `offline_evaluation_ingestion` - offline_evaluation_ingestion
     * * `organization` - organization
     * * `organization_integration` - organization_integration
     * * `organization_member` - organization_member
     * * `person` - person
     * * `plugin` - plugin
     * * `product_enablement` - product_enablement
     * * `product_tour` - product_tour
     * * `project` - project
     * * `property_definition` - property_definition
     * * `query` - query
     * * `query_performance` - query_performance
     * * `replay_scanner` - replay_scanner
     * * `review_hog` - review_hog
     * * `revenue_analytics` - revenue_analytics
     * * `session_recording` - session_recording
     * * `session_recording_playlist` - session_recording_playlist
     * * `sharing_configuration` - sharing_configuration
     * * `signal_scout` - signal_scout
     * * `stamphog` - stamphog
     * * `streamlit_app` - streamlit_app
     * * `subscription` - subscription
     * * `support_ticket` - support_ticket
     * * `survey` - survey
     * * `tagger` - tagger
     * * `ticket` - ticket
     * * `task` - task
     * * `today` - today
     * * `toolbar` - toolbar
     * * `tracing` - tracing
     * * `field_note` - field_note
     * * `uploaded_media` - uploaded_media
     * * `usage_metric` - usage_metric
     * * `user` - user
     * * `user_interview` - user_interview
     * * `vision_action` - vision_action
     * * `vision_alert` - vision_alert
     * * `visual_review` - visual_review
     * * `warehouse_objects` - warehouse_objects
     * * `warehouse_table` - warehouse_table
     * * `warehouse_view` - warehouse_view
     * * `web_analytics` - web_analytics
     * * `webhook` - webhook
     * * `wizard_session` - wizard_session
     * * `wizard_run` - wizard_run */
    resource: ScopeObjectEnumApi
    /** The object's primary key. */
    resource_id: string
    /** The object's display name. Falls back to the id when it has no name. */
    name: string
    /**
     * The object's short id, for models that link by one (insights, notebooks).
     * @nullable
     */
    short_id: string | null
    /** The level the rule grants or restricts to. */
    access_level: string
}

export interface AccessControlObjectRulesResponseApi {
    /** The subject's object rules, sorted by resource and name. */
    results: AccessControlObjectRuleApi[]
}

/**
 * A stored rule on one property definition, as configured for a subject.
 */
export interface AccessControlPropertyRuleApi {
    /** The property definition id. */
    property_definition_id: string
    /** The property name. */
    property: string
    /** Whether the property is a `person` or an `event` property. */
    property_type: string
    /** The rule's level: `none`, `read` or `read_write`. */
    access_level: string
}

export interface AccessControlPropertyRulesResponseApi {
    /** The subject's property rules, sorted by property type and name. */
    results: AccessControlPropertyRuleApi[]
}

/**
 * * `account` - account
 * * `action` - action
 * * `activity_log` - activity_log
 * * `ai_observability_clusters` - ai_observability_clusters
 * * `business_knowledge` - business_knowledge
 * * `customer_analytics` - customer_analytics
 * * `customer_journey` - customer_journey
 * * `customer_task` - customer_task
 * * `dashboard` - dashboard
 * * `dashboard_template` - dashboard_template
 * * `data_catalog` - data_catalog
 * * `data_deletion` - data_deletion
 * * `dataset` - dataset
 * * `early_access_feature` - early_access_feature
 * * `endpoint` - endpoint
 * * `error_tracking` - error_tracking
 * * `evaluation` - evaluation
 * * `experiment` - experiment
 * * `experiment_holdout` - experiment_holdout
 * * `experiment_saved_metric` - experiment_saved_metric
 * * `export` - export
 * * `external_data_source` - external_data_source
 * * `feature_flag` - feature_flag
 * * `heatmap` - heatmap
 * * `hog_flow` - hog_flow
 * * `insight` - insight
 * * `llm_analytics` - llm_analytics
 * * `llm_playground` - llm_playground
 * * `llm_prompt` - llm_prompt
 * * `llm_provider_key` - llm_provider_key
 * * `llm_skill` - llm_skill
 * * `logs` - logs
 * * `marketing_analytics` - marketing_analytics
 * * `mcp_analytics` - mcp_analytics
 * * `metrics` - metrics
 * * `notebook` - notebook
 * * `project` - project
 * * `property_definition` - property_definition
 * * `replay_scanner` - replay_scanner
 * * `revenue_analytics` - revenue_analytics
 * * `session_recording` - session_recording
 * * `session_recording_playlist` - session_recording_playlist
 * * `sharing_configuration` - sharing_configuration
 * * `stamphog` - stamphog
 * * `survey` - survey
 * * `tagger` - tagger
 * * `ticket` - ticket
 * * `toolbar` - toolbar
 * * `tracing` - tracing
 * * `vision_alert` - vision_alert
 * * `warehouse_objects` - warehouse_objects
 * * `warehouse_table` - warehouse_table
 * * `warehouse_view` - warehouse_view
 * * `web_analytics` - web_analytics
 */
export type RuleResourceEnumApi = (typeof RuleResourceEnumApi)[keyof typeof RuleResourceEnumApi]

export const RuleResourceEnumApi = {
    Account: 'account',
    Action: 'action',
    ActivityLog: 'activity_log',
    AiObservabilityClusters: 'ai_observability_clusters',
    BusinessKnowledge: 'business_knowledge',
    Canvas: 'canvas',
    CustomerAnalytics: 'customer_analytics',
    CustomerJourney: 'customer_journey',
    CustomerTask: 'customer_task',
    Dashboard: 'dashboard',
    DashboardTemplate: 'dashboard_template',
    DataCatalog: 'data_catalog',
    DataDeletion: 'data_deletion',
    Dataset: 'dataset',
    EarlyAccessFeature: 'early_access_feature',
    Endpoint: 'endpoint',
    ErrorTracking: 'error_tracking',
    Evaluation: 'evaluation',
    Experiment: 'experiment',
    ExperimentHoldout: 'experiment_holdout',
    ExperimentSavedMetric: 'experiment_saved_metric',
    Export: 'export',
    ExternalDataSource: 'external_data_source',
    FeatureFlag: 'feature_flag',
    Heatmap: 'heatmap',
    HogFlow: 'hog_flow',
    Insight: 'insight',
    LlmAnalytics: 'llm_analytics',
    LlmPlayground: 'llm_playground',
    LlmPrompt: 'llm_prompt',
    LlmProviderKey: 'llm_provider_key',
    LlmSkill: 'llm_skill',
    Logs: 'logs',
    MarketingAnalytics: 'marketing_analytics',
    McpAnalytics: 'mcp_analytics',
    Metrics: 'metrics',
    Notebook: 'notebook',
    Project: 'project',
    PropertyDefinition: 'property_definition',
    ReplayScanner: 'replay_scanner',
    RevenueAnalytics: 'revenue_analytics',
    SessionRecording: 'session_recording',
    SessionRecordingPlaylist: 'session_recording_playlist',
    SharingConfiguration: 'sharing_configuration',
    Stamphog: 'stamphog',
    Survey: 'survey',
    Tagger: 'tagger',
    Ticket: 'ticket',
    Toolbar: 'toolbar',
    Tracing: 'tracing',
    VisionAlert: 'vision_alert',
    WarehouseObjects: 'warehouse_objects',
    WarehouseTable: 'warehouse_table',
    WarehouseView: 'warehouse_view',
    WebAnalytics: 'web_analytics',
} as const

/**
 * The scope and level of one rule write. On its own it is the default rule, for everyone in the
 * project without a member or role rule of their own. The subclasses add the subject.
 */
export interface AccessControlRuleRequestApi {
    /** The scope of the rule: `project` for the project itself (with the project id as `resource_id`), a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.
     *
     * * `account` - account
     * * `action` - action
     * * `activity_log` - activity_log
     * * `ai_observability_clusters` - ai_observability_clusters
     * * `business_knowledge` - business_knowledge
     * * `customer_analytics` - customer_analytics
     * * `customer_journey` - customer_journey
     * * `customer_task` - customer_task
     * * `dashboard` - dashboard
     * * `dashboard_template` - dashboard_template
     * * `data_catalog` - data_catalog
     * * `data_deletion` - data_deletion
     * * `dataset` - dataset
     * * `early_access_feature` - early_access_feature
     * * `endpoint` - endpoint
     * * `error_tracking` - error_tracking
     * * `evaluation` - evaluation
     * * `experiment` - experiment
     * * `experiment_holdout` - experiment_holdout
     * * `experiment_saved_metric` - experiment_saved_metric
     * * `export` - export
     * * `external_data_source` - external_data_source
     * * `feature_flag` - feature_flag
     * * `heatmap` - heatmap
     * * `hog_flow` - hog_flow
     * * `insight` - insight
     * * `llm_analytics` - llm_analytics
     * * `llm_playground` - llm_playground
     * * `llm_prompt` - llm_prompt
     * * `llm_provider_key` - llm_provider_key
     * * `llm_skill` - llm_skill
     * * `logs` - logs
     * * `marketing_analytics` - marketing_analytics
     * * `mcp_analytics` - mcp_analytics
     * * `metrics` - metrics
     * * `notebook` - notebook
     * * `project` - project
     * * `property_definition` - property_definition
     * * `replay_scanner` - replay_scanner
     * * `revenue_analytics` - revenue_analytics
     * * `session_recording` - session_recording
     * * `session_recording_playlist` - session_recording_playlist
     * * `sharing_configuration` - sharing_configuration
     * * `stamphog` - stamphog
     * * `survey` - survey
     * * `tagger` - tagger
     * * `ticket` - ticket
     * * `toolbar` - toolbar
     * * `tracing` - tracing
     * * `vision_alert` - vision_alert
     * * `warehouse_objects` - warehouse_objects
     * * `warehouse_table` - warehouse_table
     * * `warehouse_view` - warehouse_view
     * * `web_analytics` - web_analytics */
    resource: RuleResourceEnumApi
    /**
     * The object the rule applies to: the project id for a project rule, an object's primary key for a rule on one object, or a property definition id when `resource` is `property_definition`. Omit it only for a rule on a whole resource type.
     * @nullable
     */
    resource_id?: string | null
    /**
     * The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.
     * @nullable
     */
    access_level: string | null
}

/**
 * One stored rule, the same shape for object, resource, project and property rules.
 */
export interface AccessControlStoredRuleApi {
    /** The rule's scope, as sent in the request. */
    resource: string
    /**
     * The object the rule applies to: the project id for a project rule, an object's primary key, or a property definition id. Null for a resource-type rule.
     * @nullable
     */
    resource_id: string | null
    /** The stored level. */
    access_level: string
    /**
     * The organization membership the rule is for. Null unless it is a member rule.
     * @nullable
     */
    member_id: string | null
    /**
     * The role the rule is for. Null unless it is a role rule.
     * @nullable
     */
    role_id: string | null
}

export interface AccessControlResourceDefaultApi {
    /**
     * The stored default level for this resource type. Null when the PostHog default applies.
     * @nullable
     */
    access_level: string | null
    /** The lowest level this resource type allows. */
    minimum: string
    /** The highest level this resource type allows. */
    maximum: string
}

/**
 * The default level per resource type, keyed by resource name.
 */
export type AccessControlDefaultsResponseApiResourceAccessLevels = { [key: string]: AccessControlResourceDefaultApi }

export interface AccessControlObjectRuleResourceApi {
    /** A resource type that supports rules on single objects.
     *
     * * `action` - action
     * * `access_control` - access_control
     * * `account` - account
     * * `activity_log` - activity_log
     * * `alert` - alert
     * * `annotation` - annotation
     * * `approvals` - approvals
     * * `autoresearch` - autoresearch
     * * `batch_export` - batch_export
     * * `batch_import` - batch_import
     * * `batch_import_support` - batch_import_support
     * * `billing` - billing
     * * `business_knowledge` - business_knowledge
     * * `canvas` - canvas
     * * `cohort` - cohort
     * * `comment` - comment
     * * `conversation` - conversation
     * * `cross_project_dashboard` - cross_project_dashboard
     * * `customer_analytics` - customer_analytics
     * * `customer_task` - customer_task
     * * `customer_journey` - customer_journey
     * * `customer_profile_config` - customer_profile_config
     * * `data_catalog` - data_catalog
     * * `data_catalog_approval` - data_catalog_approval
     * * `data_deletion` - data_deletion
     * * `dashboard` - dashboard
     * * `event_filter` - event_filter
     * * `dashboard_template` - dashboard_template
     * * `dataset` - dataset
     * * `early_access_feature` - early_access_feature
     * * `endpoint` - endpoint
     * * `engineering_analytics` - engineering_analytics
     * * `error_tracking` - error_tracking
     * * `evaluation` - evaluation
     * * `element` - element
     * * `event_definition` - event_definition
     * * `experiment` - experiment
     * * `experiment_holdout` - experiment_holdout
     * * `experiment_saved_metric` - experiment_saved_metric
     * * `export` - export
     * * `external_data_schema` - external_data_schema
     * * `external_data_source` - external_data_source
     * * `feature_flag` - feature_flag
     * * `file_system` - file_system
     * * `file_system_shortcut` - file_system_shortcut
     * * `group` - group
     * * `health_issue` - health_issue
     * * `heatmap` - heatmap
     * * `hog_flow` - hog_flow
     * * `hog_function` - hog_function
     * * `ingestion_warning` - ingestion_warning
     * * `insight` - insight
     * * `insight_variable` - insight_variable
     * * `integration` - integration
     * * `legal_document` - legal_document
     * * `link` - link
     * * `live_debugger` - live_debugger
     * * `llm_analytics` - llm_analytics
     * * `ai_observability_clusters` - ai_observability_clusters
     * * `llm_gateway` - llm_gateway
     * * `llm_playground` - llm_playground
     * * `llm_prompt` - llm_prompt
     * * `llm_provider_key` - llm_provider_key
     * * `llm_skill` - llm_skill
     * * `logs` - logs
     * * `loop` - loop
     * * `marketing_analytics` - marketing_analytics
     * * `mcp_analytics` - mcp_analytics
     * * `mcp_registry` - mcp_registry
     * * `metrics` - metrics
     * * `notebook` - notebook
     * * `offline_evaluation_ingestion` - offline_evaluation_ingestion
     * * `organization` - organization
     * * `organization_integration` - organization_integration
     * * `organization_member` - organization_member
     * * `person` - person
     * * `plugin` - plugin
     * * `product_enablement` - product_enablement
     * * `product_tour` - product_tour
     * * `project` - project
     * * `property_definition` - property_definition
     * * `query` - query
     * * `query_performance` - query_performance
     * * `replay_scanner` - replay_scanner
     * * `review_hog` - review_hog
     * * `revenue_analytics` - revenue_analytics
     * * `session_recording` - session_recording
     * * `session_recording_playlist` - session_recording_playlist
     * * `sharing_configuration` - sharing_configuration
     * * `signal_scout` - signal_scout
     * * `stamphog` - stamphog
     * * `streamlit_app` - streamlit_app
     * * `subscription` - subscription
     * * `support_ticket` - support_ticket
     * * `survey` - survey
     * * `tagger` - tagger
     * * `ticket` - ticket
     * * `task` - task
     * * `today` - today
     * * `toolbar` - toolbar
     * * `tracing` - tracing
     * * `field_note` - field_note
     * * `uploaded_media` - uploaded_media
     * * `usage_metric` - usage_metric
     * * `user` - user
     * * `user_interview` - user_interview
     * * `vision_action` - vision_action
     * * `vision_alert` - vision_alert
     * * `visual_review` - visual_review
     * * `warehouse_objects` - warehouse_objects
     * * `warehouse_table` - warehouse_table
     * * `warehouse_view` - warehouse_view
     * * `web_analytics` - web_analytics
     * * `webhook` - webhook
     * * `wizard_session` - wizard_session
     * * `wizard_run` - wizard_run */
    resource: ScopeObjectEnumApi
    /** The levels an object rule on this resource type accepts, lowest first. */
    available_access_levels: string[]
    /** The lowest level an object rule on this resource can set. */
    minimum_access_level: string
}

/**
 * The project's defaults: what everyone without a rule of their own gets.
 */
export interface AccessControlDefaultsResponseApi {
    /** The project access levels, lowest first. */
    available_project_levels: string[]
    /** The resource access levels, lowest first. */
    available_resource_levels: string[]
    /** Whether the caller may change access rules in this project. */
    can_edit: boolean
    /** The default project access level for members. */
    project_access_level: string
    /** The default level per resource type, keyed by resource name. */
    resource_access_levels: AccessControlDefaultsResponseApiResourceAccessLevels
    /** The resource types that accept rules on single objects, with the levels each accepts. */
    object_rule_resources: AccessControlObjectRuleResourceApi[]
}

/**
 * A rule for one organization member.
 */
export interface AccessControlMemberRuleRequestApi {
    /** The scope of the rule: `project` for the project itself (with the project id as `resource_id`), a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.
     *
     * * `account` - account
     * * `action` - action
     * * `activity_log` - activity_log
     * * `ai_observability_clusters` - ai_observability_clusters
     * * `business_knowledge` - business_knowledge
     * * `customer_analytics` - customer_analytics
     * * `customer_journey` - customer_journey
     * * `customer_task` - customer_task
     * * `dashboard` - dashboard
     * * `dashboard_template` - dashboard_template
     * * `data_catalog` - data_catalog
     * * `data_deletion` - data_deletion
     * * `dataset` - dataset
     * * `early_access_feature` - early_access_feature
     * * `endpoint` - endpoint
     * * `error_tracking` - error_tracking
     * * `evaluation` - evaluation
     * * `experiment` - experiment
     * * `experiment_holdout` - experiment_holdout
     * * `experiment_saved_metric` - experiment_saved_metric
     * * `export` - export
     * * `external_data_source` - external_data_source
     * * `feature_flag` - feature_flag
     * * `heatmap` - heatmap
     * * `hog_flow` - hog_flow
     * * `insight` - insight
     * * `llm_analytics` - llm_analytics
     * * `llm_playground` - llm_playground
     * * `llm_prompt` - llm_prompt
     * * `llm_provider_key` - llm_provider_key
     * * `llm_skill` - llm_skill
     * * `logs` - logs
     * * `marketing_analytics` - marketing_analytics
     * * `mcp_analytics` - mcp_analytics
     * * `metrics` - metrics
     * * `notebook` - notebook
     * * `project` - project
     * * `property_definition` - property_definition
     * * `replay_scanner` - replay_scanner
     * * `revenue_analytics` - revenue_analytics
     * * `session_recording` - session_recording
     * * `session_recording_playlist` - session_recording_playlist
     * * `sharing_configuration` - sharing_configuration
     * * `stamphog` - stamphog
     * * `survey` - survey
     * * `tagger` - tagger
     * * `ticket` - ticket
     * * `toolbar` - toolbar
     * * `tracing` - tracing
     * * `vision_alert` - vision_alert
     * * `warehouse_objects` - warehouse_objects
     * * `warehouse_table` - warehouse_table
     * * `warehouse_view` - warehouse_view
     * * `web_analytics` - web_analytics */
    resource: RuleResourceEnumApi
    /**
     * The object the rule applies to: the project id for a project rule, an object's primary key for a rule on one object, or a property definition id when `resource` is `property_definition`. Omit it only for a rule on a whole resource type.
     * @nullable
     */
    resource_id?: string | null
    /**
     * The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.
     * @nullable
     */
    access_level: string | null
    /** The organization membership id, as `organization_membership_id` in the members endpoint. */
    member_id: string
}

export interface AccessControlMemberUserApi {
    /** The user's UUID. */
    uuid: string
    /** The user's first name. */
    first_name: string
    /** The user's last name. */
    last_name: string
    /** The user's email. */
    email: string
}

/**
 * * `1` - member
 * * `8` - administrator
 * * `15` - owner
 */
export type OrganizationMembershipLevelEnumApi =
    (typeof OrganizationMembershipLevelEnumApi)[keyof typeof OrganizationMembershipLevelEnumApi]

export const OrganizationMembershipLevelEnumApi = {
    Number1: 1,
    Number8: 8,
    Number15: 15,
} as const

/**
 * A resolved access level with the rule that supplied it — the wire form of `ResolvedAccess`.
 */
export interface ResolvedAccessApi {
    /** The access level that applies. */
    access_level: string
    /** How the level was derived: a rule on the object, its parent object, the resource, the parent resource, the PostHog default, an organization admin's or a creator's full access, or organization membership when the object is the organization itself.
     *
     * * `object` - object
     * * `parent_object` - parent_object
     * * `resource` - resource
     * * `parent_resource` - parent_resource
     * * `system_default` - system_default
     * * `org_admin` - org_admin
     * * `creator` - creator
     * * `org_membership` - org_membership */
    source: ResolvedAccessSourceEnumApi
    /** Whose rule decided: a member's own, a role's, or the default for everyone in the project. Null when no rule did.
     *
     * * `member` - member
     * * `role` - role
     * * `default` - default */
    source_subject: ResolvedAccessSourceSubjectEnumApi | null
    /** The resource the deciding rule belongs to.
     *
     * * `action` - action
     * * `access_control` - access_control
     * * `account` - account
     * * `activity_log` - activity_log
     * * `alert` - alert
     * * `annotation` - annotation
     * * `approvals` - approvals
     * * `autoresearch` - autoresearch
     * * `batch_export` - batch_export
     * * `batch_import` - batch_import
     * * `batch_import_support` - batch_import_support
     * * `billing` - billing
     * * `business_knowledge` - business_knowledge
     * * `canvas` - canvas
     * * `cohort` - cohort
     * * `comment` - comment
     * * `conversation` - conversation
     * * `cross_project_dashboard` - cross_project_dashboard
     * * `customer_analytics` - customer_analytics
     * * `customer_task` - customer_task
     * * `customer_journey` - customer_journey
     * * `customer_profile_config` - customer_profile_config
     * * `data_catalog` - data_catalog
     * * `data_catalog_approval` - data_catalog_approval
     * * `data_deletion` - data_deletion
     * * `dashboard` - dashboard
     * * `event_filter` - event_filter
     * * `dashboard_template` - dashboard_template
     * * `dataset` - dataset
     * * `early_access_feature` - early_access_feature
     * * `endpoint` - endpoint
     * * `engineering_analytics` - engineering_analytics
     * * `error_tracking` - error_tracking
     * * `evaluation` - evaluation
     * * `element` - element
     * * `event_definition` - event_definition
     * * `experiment` - experiment
     * * `experiment_holdout` - experiment_holdout
     * * `experiment_saved_metric` - experiment_saved_metric
     * * `export` - export
     * * `external_data_schema` - external_data_schema
     * * `external_data_source` - external_data_source
     * * `feature_flag` - feature_flag
     * * `file_system` - file_system
     * * `file_system_shortcut` - file_system_shortcut
     * * `group` - group
     * * `health_issue` - health_issue
     * * `heatmap` - heatmap
     * * `hog_flow` - hog_flow
     * * `hog_function` - hog_function
     * * `ingestion_warning` - ingestion_warning
     * * `insight` - insight
     * * `insight_variable` - insight_variable
     * * `integration` - integration
     * * `legal_document` - legal_document
     * * `link` - link
     * * `live_debugger` - live_debugger
     * * `llm_analytics` - llm_analytics
     * * `ai_observability_clusters` - ai_observability_clusters
     * * `llm_gateway` - llm_gateway
     * * `llm_playground` - llm_playground
     * * `llm_prompt` - llm_prompt
     * * `llm_provider_key` - llm_provider_key
     * * `llm_skill` - llm_skill
     * * `logs` - logs
     * * `loop` - loop
     * * `marketing_analytics` - marketing_analytics
     * * `mcp_analytics` - mcp_analytics
     * * `mcp_registry` - mcp_registry
     * * `metrics` - metrics
     * * `notebook` - notebook
     * * `offline_evaluation_ingestion` - offline_evaluation_ingestion
     * * `organization` - organization
     * * `organization_integration` - organization_integration
     * * `organization_member` - organization_member
     * * `person` - person
     * * `plugin` - plugin
     * * `product_enablement` - product_enablement
     * * `product_tour` - product_tour
     * * `project` - project
     * * `property_definition` - property_definition
     * * `query` - query
     * * `query_performance` - query_performance
     * * `replay_scanner` - replay_scanner
     * * `review_hog` - review_hog
     * * `revenue_analytics` - revenue_analytics
     * * `session_recording` - session_recording
     * * `session_recording_playlist` - session_recording_playlist
     * * `sharing_configuration` - sharing_configuration
     * * `signal_scout` - signal_scout
     * * `stamphog` - stamphog
     * * `streamlit_app` - streamlit_app
     * * `subscription` - subscription
     * * `support_ticket` - support_ticket
     * * `survey` - survey
     * * `tagger` - tagger
     * * `ticket` - ticket
     * * `task` - task
     * * `today` - today
     * * `toolbar` - toolbar
     * * `tracing` - tracing
     * * `field_note` - field_note
     * * `uploaded_media` - uploaded_media
     * * `usage_metric` - usage_metric
     * * `user` - user
     * * `user_interview` - user_interview
     * * `vision_action` - vision_action
     * * `vision_alert` - vision_alert
     * * `visual_review` - visual_review
     * * `warehouse_objects` - warehouse_objects
     * * `warehouse_table` - warehouse_table
     * * `warehouse_view` - warehouse_view
     * * `web_analytics` - web_analytics
     * * `webhook` - webhook
     * * `wizard_session` - wizard_session
     * * `wizard_run` - wizard_run */
    source_resource: ScopeObjectEnumApi
    /**
     * The deciding rule's object id, when it is an object-level rule (e.g. the source a table inherits from).
     * @nullable
     */
    source_resource_id: string | null
}

/**
 * One subject's access to one scope (the project, or a whole resource type): what is stored,
 * what is enforced, and where the enforced level comes from.
 */
export interface SubjectAccessEntryApi {
    /**
     * The subject's own stored rule for this scope. Null when the subject has no rule of its own here.
     * @nullable
     */
    access_level: string | null
    /**
     * The level that is enforced for the subject after defaults, roles and bypasses are resolved. Null when nothing resolves for this scope.
     * @nullable
     */
    effective_access_level: string | null
    /** The level the subject falls back to without a rule of its own, with the rule that supplies it. Read `source` and `source_subject` to tell a role rule from the project default, or an organization admin's full access. */
    inherited_access: ResolvedAccessApi | null
    /** The lowest level this scope allows. */
    minimum: string
    /** The highest level this scope allows. */
    maximum: string
}

/**
 * Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`).
 */
export type AccessControlMemberAccessApiResources = { [key: string]: SubjectAccessEntryApi }

/**
 * A member's resolved access to the project and to every resource type in it.
 */
export interface AccessControlMemberAccessApi {
    /** The organization membership id. Use it as `member_id` on the member rule endpoints. */
    organization_membership_id: string
    /** The member's identity. */
    user: AccessControlMemberUserApi
    /** The member's organization level: 1 member, 8 admin, 15 owner. Admins and owners have full access to everything.
     *
     * * `1` - member
     * * `8` - administrator
     * * `15` - owner */
    organization_level: OrganizationMembershipLevelEnumApi
    /** The roles the member is in. Use them as `role_id` on the role rule endpoints. */
    role_ids: string[]
    /** Access to the project itself. */
    project: SubjectAccessEntryApi
    /** Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`). */
    resources: AccessControlMemberAccessApiResources
}

export interface AccessControlMembersResponseApi {
    /** The project access levels, lowest first. */
    available_project_levels: string[]
    /** The resource access levels, lowest first. */
    available_resource_levels: string[]
    /** Whether the caller may change access rules in this project. */
    can_edit: boolean
    /** One entry per organization member. */
    results: AccessControlMemberAccessApi[]
}

/**
 * A rule for every member of one role.
 */
export interface AccessControlRoleRuleRequestApi {
    /** The scope of the rule: `project` for the project itself (with the project id as `resource_id`), a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.
     *
     * * `account` - account
     * * `action` - action
     * * `activity_log` - activity_log
     * * `ai_observability_clusters` - ai_observability_clusters
     * * `business_knowledge` - business_knowledge
     * * `customer_analytics` - customer_analytics
     * * `customer_journey` - customer_journey
     * * `customer_task` - customer_task
     * * `dashboard` - dashboard
     * * `dashboard_template` - dashboard_template
     * * `data_catalog` - data_catalog
     * * `data_deletion` - data_deletion
     * * `dataset` - dataset
     * * `early_access_feature` - early_access_feature
     * * `endpoint` - endpoint
     * * `error_tracking` - error_tracking
     * * `evaluation` - evaluation
     * * `experiment` - experiment
     * * `experiment_holdout` - experiment_holdout
     * * `experiment_saved_metric` - experiment_saved_metric
     * * `export` - export
     * * `external_data_source` - external_data_source
     * * `feature_flag` - feature_flag
     * * `heatmap` - heatmap
     * * `hog_flow` - hog_flow
     * * `insight` - insight
     * * `llm_analytics` - llm_analytics
     * * `llm_playground` - llm_playground
     * * `llm_prompt` - llm_prompt
     * * `llm_provider_key` - llm_provider_key
     * * `llm_skill` - llm_skill
     * * `logs` - logs
     * * `marketing_analytics` - marketing_analytics
     * * `mcp_analytics` - mcp_analytics
     * * `metrics` - metrics
     * * `notebook` - notebook
     * * `project` - project
     * * `property_definition` - property_definition
     * * `replay_scanner` - replay_scanner
     * * `revenue_analytics` - revenue_analytics
     * * `session_recording` - session_recording
     * * `session_recording_playlist` - session_recording_playlist
     * * `sharing_configuration` - sharing_configuration
     * * `stamphog` - stamphog
     * * `survey` - survey
     * * `tagger` - tagger
     * * `ticket` - ticket
     * * `toolbar` - toolbar
     * * `tracing` - tracing
     * * `vision_alert` - vision_alert
     * * `warehouse_objects` - warehouse_objects
     * * `warehouse_table` - warehouse_table
     * * `warehouse_view` - warehouse_view
     * * `web_analytics` - web_analytics */
    resource: RuleResourceEnumApi
    /**
     * The object the rule applies to: the project id for a project rule, an object's primary key for a rule on one object, or a property definition id when `resource` is `property_definition`. Omit it only for a rule on a whole resource type.
     * @nullable
     */
    resource_id?: string | null
    /**
     * The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.
     * @nullable
     */
    access_level: string | null
    /** The role id, as `role_id` in the roles endpoint. */
    role_id: string
}

/**
 * Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`).
 */
export type AccessControlRoleAccessApiResources = { [key: string]: SubjectAccessEntryApi }

/**
 * A role's resolved access to the project and to every resource type in it.
 */
export interface AccessControlRoleAccessApi {
    /** The role id. Use it as `role_id` on the role rule endpoints. */
    role_id: string
    /** The role's name. */
    role_name: string
    /** Access to the project itself. */
    project: SubjectAccessEntryApi
    /** Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`). */
    resources: AccessControlRoleAccessApiResources
}

export interface AccessControlRolesResponseApi {
    /** The project access levels, lowest first. */
    available_project_levels: string[]
    /** The resource access levels, lowest first. */
    available_resource_levels: string[]
    /** Whether the caller may change access rules in this project. */
    can_edit: boolean
    /** One entry per role in the organization. */
    results: AccessControlRoleAccessApi[]
}

/**
 * * `read_write` - read_write
 * * `read` - read
 * * `none` - none
 */
export type AccessLevelEnumApi = (typeof AccessLevelEnumApi)[keyof typeof AccessLevelEnumApi]

export const AccessLevelEnumApi = {
    ReadWrite: 'read_write',
    Read: 'read',
    None: 'none',
} as const

/**
 * Serializes a single access control rule DTO.
 */
export interface PropertyAccessControlRuleApi {
    readonly id: string
    /** The access level for this rule.
     *
     * * `read_write` - read_write
     * * `read` - read
     * * `none` - none */
    access_level: AccessLevelEnumApi
    /**
     * The organization member UUID this rule applies to, if any.
     * @nullable
     */
    organization_member: string | null
    /**
     * The role UUID this rule applies to, if any.
     * @nullable
     */
    role: string | null
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
    readonly updated_at: string
}

/**
 * Serializes the aggregate state for a property definition.
 *
 * Preserves the existing API shape: ``access_controls`` is the list
 * of rules, plus the available levels and the computed default.
 */
export interface PropertyAccessControlStateApi {
    /** List of all access control rules for this property definition. */
    access_controls: PropertyAccessControlRuleApi[]
    /** Available access levels that can be assigned. */
    available_access_levels: string[]
    /** The default access level when no rules match. */
    default_access_level: string
}

/**
 * * `$ai_trace_id` - $ai_trace_id
 * * `$ai_session_id` - $ai_session_id
 * * `$ai_parent_id` - $ai_parent_id
 * * `$ai_span_id` - $ai_span_id
 * * `$ai_span_type` - $ai_span_type
 * * `$ai_generation_id` - $ai_generation_id
 * * `$ai_experiment_id` - $ai_experiment_id
 * * `$ai_span_name` - $ai_span_name
 * * `$ai_trace_name` - $ai_trace_name
 * * `$ai_prompt_name` - $ai_prompt_name
 * * `$ai_model` - $ai_model
 * * `$ai_provider` - $ai_provider
 * * `$ai_framework` - $ai_framework
 * * `$ai_total_tokens` - $ai_total_tokens
 * * `$ai_input_tokens` - $ai_input_tokens
 * * `$ai_output_tokens` - $ai_output_tokens
 * * `$ai_text_input_tokens` - $ai_text_input_tokens
 * * `$ai_text_output_tokens` - $ai_text_output_tokens
 * * `$ai_image_input_tokens` - $ai_image_input_tokens
 * * `$ai_image_output_tokens` - $ai_image_output_tokens
 * * `$ai_audio_input_tokens` - $ai_audio_input_tokens
 * * `$ai_audio_output_tokens` - $ai_audio_output_tokens
 * * `$ai_video_input_tokens` - $ai_video_input_tokens
 * * `$ai_video_output_tokens` - $ai_video_output_tokens
 * * `$ai_reasoning_tokens` - $ai_reasoning_tokens
 * * `$ai_cache_read_input_tokens` - $ai_cache_read_input_tokens
 * * `$ai_cache_creation_input_tokens` - $ai_cache_creation_input_tokens
 * * `$ai_web_search_count` - $ai_web_search_count
 * * `$ai_input_cost_usd` - $ai_input_cost_usd
 * * `$ai_output_cost_usd` - $ai_output_cost_usd
 * * `$ai_total_cost_usd` - $ai_total_cost_usd
 * * `$ai_request_cost_usd` - $ai_request_cost_usd
 * * `$ai_web_search_cost_usd` - $ai_web_search_cost_usd
 * * `$ai_audio_cost_usd` - $ai_audio_cost_usd
 * * `$ai_image_cost_usd` - $ai_image_cost_usd
 * * `$ai_video_cost_usd` - $ai_video_cost_usd
 * * `$ai_latency` - $ai_latency
 * * `$ai_time_to_first_token` - $ai_time_to_first_token
 * * `$ai_is_error` - $ai_is_error
 * * `$ai_error` - $ai_error
 * * `$ai_error_type` - $ai_error_type
 * * `$ai_error_normalized` - $ai_error_normalized
 * * `$ai_input` - $ai_input
 * * `$ai_output` - $ai_output
 * * `$ai_output_choices` - $ai_output_choices
 * * `$ai_input_state` - $ai_input_state
 * * `$ai_output_state` - $ai_output_state
 * * `$ai_tools` - $ai_tools
 */
export type AIEventPropertyEnumApi = (typeof AIEventPropertyEnumApi)[keyof typeof AIEventPropertyEnumApi]

export const AIEventPropertyEnumApi = {
    AiTraceId: '$ai_trace_id',
    AiSessionId: '$ai_session_id',
    AiParentId: '$ai_parent_id',
    AiSpanId: '$ai_span_id',
    AiSpanType: '$ai_span_type',
    AiGenerationId: '$ai_generation_id',
    AiExperimentId: '$ai_experiment_id',
    AiSpanName: '$ai_span_name',
    AiTraceName: '$ai_trace_name',
    AiPromptName: '$ai_prompt_name',
    AiModel: '$ai_model',
    AiProvider: '$ai_provider',
    AiFramework: '$ai_framework',
    AiTotalTokens: '$ai_total_tokens',
    AiInputTokens: '$ai_input_tokens',
    AiOutputTokens: '$ai_output_tokens',
    AiTextInputTokens: '$ai_text_input_tokens',
    AiTextOutputTokens: '$ai_text_output_tokens',
    AiImageInputTokens: '$ai_image_input_tokens',
    AiImageOutputTokens: '$ai_image_output_tokens',
    AiAudioInputTokens: '$ai_audio_input_tokens',
    AiAudioOutputTokens: '$ai_audio_output_tokens',
    AiVideoInputTokens: '$ai_video_input_tokens',
    AiVideoOutputTokens: '$ai_video_output_tokens',
    AiReasoningTokens: '$ai_reasoning_tokens',
    AiCacheReadInputTokens: '$ai_cache_read_input_tokens',
    AiCacheCreationInputTokens: '$ai_cache_creation_input_tokens',
    AiWebSearchCount: '$ai_web_search_count',
    AiInputCostUsd: '$ai_input_cost_usd',
    AiOutputCostUsd: '$ai_output_cost_usd',
    AiTotalCostUsd: '$ai_total_cost_usd',
    AiRequestCostUsd: '$ai_request_cost_usd',
    AiWebSearchCostUsd: '$ai_web_search_cost_usd',
    AiAudioCostUsd: '$ai_audio_cost_usd',
    AiImageCostUsd: '$ai_image_cost_usd',
    AiVideoCostUsd: '$ai_video_cost_usd',
    AiLatency: '$ai_latency',
    AiTimeToFirstToken: '$ai_time_to_first_token',
    AiIsError: '$ai_is_error',
    AiError: '$ai_error',
    AiErrorType: '$ai_error_type',
    AiErrorNormalized: '$ai_error_normalized',
    AiInput: '$ai_input',
    AiOutput: '$ai_output',
    AiOutputChoices: '$ai_output_choices',
    AiInputState: '$ai_input_state',
    AiOutputState: '$ai_output_state',
    AiTools: '$ai_tools',
} as const

/**
 * Request body for upserting a rule (create or update).
 */
export interface PropertyAccessControlUpdateApi {
    /** The existing property definition ID. Provide this or ai_property. */
    property_definition_id?: string
    /** A built-in AI event property. Creates its definition if missing. Provide this or property_definition_id.
     *
     * * `$ai_trace_id` - $ai_trace_id
     * * `$ai_session_id` - $ai_session_id
     * * `$ai_parent_id` - $ai_parent_id
     * * `$ai_span_id` - $ai_span_id
     * * `$ai_span_type` - $ai_span_type
     * * `$ai_generation_id` - $ai_generation_id
     * * `$ai_experiment_id` - $ai_experiment_id
     * * `$ai_span_name` - $ai_span_name
     * * `$ai_trace_name` - $ai_trace_name
     * * `$ai_prompt_name` - $ai_prompt_name
     * * `$ai_model` - $ai_model
     * * `$ai_provider` - $ai_provider
     * * `$ai_framework` - $ai_framework
     * * `$ai_total_tokens` - $ai_total_tokens
     * * `$ai_input_tokens` - $ai_input_tokens
     * * `$ai_output_tokens` - $ai_output_tokens
     * * `$ai_text_input_tokens` - $ai_text_input_tokens
     * * `$ai_text_output_tokens` - $ai_text_output_tokens
     * * `$ai_image_input_tokens` - $ai_image_input_tokens
     * * `$ai_image_output_tokens` - $ai_image_output_tokens
     * * `$ai_audio_input_tokens` - $ai_audio_input_tokens
     * * `$ai_audio_output_tokens` - $ai_audio_output_tokens
     * * `$ai_video_input_tokens` - $ai_video_input_tokens
     * * `$ai_video_output_tokens` - $ai_video_output_tokens
     * * `$ai_reasoning_tokens` - $ai_reasoning_tokens
     * * `$ai_cache_read_input_tokens` - $ai_cache_read_input_tokens
     * * `$ai_cache_creation_input_tokens` - $ai_cache_creation_input_tokens
     * * `$ai_web_search_count` - $ai_web_search_count
     * * `$ai_input_cost_usd` - $ai_input_cost_usd
     * * `$ai_output_cost_usd` - $ai_output_cost_usd
     * * `$ai_total_cost_usd` - $ai_total_cost_usd
     * * `$ai_request_cost_usd` - $ai_request_cost_usd
     * * `$ai_web_search_cost_usd` - $ai_web_search_cost_usd
     * * `$ai_audio_cost_usd` - $ai_audio_cost_usd
     * * `$ai_image_cost_usd` - $ai_image_cost_usd
     * * `$ai_video_cost_usd` - $ai_video_cost_usd
     * * `$ai_latency` - $ai_latency
     * * `$ai_time_to_first_token` - $ai_time_to_first_token
     * * `$ai_is_error` - $ai_is_error
     * * `$ai_error` - $ai_error
     * * `$ai_error_type` - $ai_error_type
     * * `$ai_error_normalized` - $ai_error_normalized
     * * `$ai_input` - $ai_input
     * * `$ai_output` - $ai_output
     * * `$ai_output_choices` - $ai_output_choices
     * * `$ai_input_state` - $ai_input_state
     * * `$ai_output_state` - $ai_output_state
     * * `$ai_tools` - $ai_tools */
    ai_property?: AIEventPropertyEnumApi
    /** The access level to set for this rule.
     *
     * * `read_write` - read_write
     * * `read` - read
     * * `none` - none */
    access_level: AccessLevelEnumApi
    /**
     * The organization member UUID to set an override for.
     * @nullable
     */
    organization_member?: string | null
    /**
     * The role UUID to set an override for.
     * @nullable
     */
    role?: string | null
}

export type MembersProjectAccessRetrieveParams = {
    /**
     * Narrow the list to one organization membership id.
     */
    member_id?: string
}

export type OrganizationsProjectsAccessControlMemberObjectsRetrieveParams = {
    /**
     * The organization membership id, as `organization_membership_id` in the members endpoint.
     */
    member_id: string
}

export type OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams = {
    /**
     * The organization membership id, as `organization_membership_id` in the members endpoint.
     */
    member_id: string
}

export type OrganizationsProjectsAccessControlMembersRetrieveParams = {
    /**
     * Narrow the list to one organization membership id.
     */
    member_id?: string
}

export type OrganizationsProjectsAccessControlRoleObjectsRetrieveParams = {
    /**
     * The role id, as `role_id` in the roles endpoint.
     */
    role_id: string
}

export type OrganizationsProjectsAccessControlRolePropertiesRetrieveParams = {
    /**
     * The role id, as `role_id` in the roles endpoint.
     */
    role_id: string
}

export type OrganizationsProjectsAccessControlRolesRetrieveParams = {
    /**
     * Narrow the list to one role.
     */
    role_id?: string
}

export type PropertyAccessControlsRetrieveParams = {
    /**
     * The property definition ID to fetch access control rules for.
     */
    property_definition_id: string
}

export type PropertyAccessControlsDestroyParams = {
    /**
     * The organization member UUID whose override should be deleted.
     */
    organization_member?: string
    /**
     * The property definition ID the rule applies to.
     */
    property_definition_id: string
    /**
     * The role UUID whose override should be deleted.
     */
    role?: string
}
