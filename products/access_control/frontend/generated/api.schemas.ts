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
    /** The resource the deciding rule belongs to. */
    source_resource: string
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
    /** The object's resource type, for example `dashboard`. */
    resource: string
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
    /** A resource type that supports rules on single objects. */
    resource: string
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
    /** The resource the deciding rule belongs to. */
    source_resource: string
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
 * Request body for upserting a rule (create or update).
 */
export interface PropertyAccessControlUpdateApi {
    /** The property definition ID this rule applies to. */
    property_definition_id: string
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
