/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Set or clear the rule everyone in the project gets for a scope, unless a member or role rule of their own applies. The scope is the project (`resource: project`), a whole resource type, one object, or one property definition. A null `access_level` removes the rule.
 */
export const OrganizationsProjectsAccessControlDefaultRulesUpdateBody = /* @__PURE__ */ zod
    .object({
        resource: zod
            .enum([
                'account',
                'action',
                'activity_log',
                'ai_observability_clusters',
                'customer_analytics',
                'customer_journey',
                'customer_task',
                'dashboard',
                'dashboard_template',
                'data_catalog',
                'dataset',
                'early_access_feature',
                'endpoint',
                'error_tracking',
                'evaluation',
                'experiment',
                'experiment_holdout',
                'experiment_saved_metric',
                'export',
                'external_data_source',
                'feature_flag',
                'heatmap',
                'hog_flow',
                'insight',
                'llm_analytics',
                'llm_playground',
                'llm_prompt',
                'llm_provider_key',
                'llm_skill',
                'logs',
                'marketing_analytics',
                'mcp_analytics',
                'metrics',
                'notebook',
                'project',
                'property_definition',
                'replay_scanner',
                'revenue_analytics',
                'session_recording',
                'session_recording_playlist',
                'sharing_configuration',
                'stamphog',
                'survey',
                'tagger',
                'ticket',
                'toolbar',
                'tracing',
                'vision_alert',
                'warehouse_objects',
                'warehouse_table',
                'warehouse_view',
                'web_analytics',
            ])
            .describe(
                '\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            )
            .describe(
                'The scope of the rule: `project` for the project itself, a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.\n\n\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            ),
        resource_id: zod
            .string()
            .nullish()
            .describe(
                "The object the rule applies to: an object's primary key, or a property definition id when `resource` is `property_definition`. Omit it for a rule on the whole resource type or on the project."
            ),
        access_level: zod
            .string()
            .nullable()
            .describe(
                'The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.'
            ),
    })
    .describe('A rule for everyone in the project without a member or role rule of their own.')

/**
 * Set or clear one member's rule for a scope. A member rule applies to that person only and takes precedence over their role rules and the default. The scope is the project, a whole resource type, one object, or one property definition. A null `access_level` removes the rule.
 */
export const OrganizationsProjectsAccessControlMemberRulesUpdateBody = /* @__PURE__ */ zod
    .object({
        resource: zod
            .enum([
                'account',
                'action',
                'activity_log',
                'ai_observability_clusters',
                'customer_analytics',
                'customer_journey',
                'customer_task',
                'dashboard',
                'dashboard_template',
                'data_catalog',
                'dataset',
                'early_access_feature',
                'endpoint',
                'error_tracking',
                'evaluation',
                'experiment',
                'experiment_holdout',
                'experiment_saved_metric',
                'export',
                'external_data_source',
                'feature_flag',
                'heatmap',
                'hog_flow',
                'insight',
                'llm_analytics',
                'llm_playground',
                'llm_prompt',
                'llm_provider_key',
                'llm_skill',
                'logs',
                'marketing_analytics',
                'mcp_analytics',
                'metrics',
                'notebook',
                'project',
                'property_definition',
                'replay_scanner',
                'revenue_analytics',
                'session_recording',
                'session_recording_playlist',
                'sharing_configuration',
                'stamphog',
                'survey',
                'tagger',
                'ticket',
                'toolbar',
                'tracing',
                'vision_alert',
                'warehouse_objects',
                'warehouse_table',
                'warehouse_view',
                'web_analytics',
            ])
            .describe(
                '\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            )
            .describe(
                'The scope of the rule: `project` for the project itself, a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.\n\n\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            ),
        resource_id: zod
            .string()
            .nullish()
            .describe(
                "The object the rule applies to: an object's primary key, or a property definition id when `resource` is `property_definition`. Omit it for a rule on the whole resource type or on the project."
            ),
        access_level: zod
            .string()
            .nullable()
            .describe(
                'The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.'
            ),
        member_id: zod
            .uuid()
            .describe('The organization membership id, as `organization_membership_id` in the members endpoint.'),
    })
    .describe('A rule for one organization member.')

/**
 * Set or clear one role's rule for a scope. A role rule applies to every member of the role and takes precedence over the default. Requires the role-based access feature. The scope is the project, a whole resource type, one object, or one property definition. A null `access_level` removes the rule.
 */
export const OrganizationsProjectsAccessControlRoleRulesUpdateBody = /* @__PURE__ */ zod
    .object({
        resource: zod
            .enum([
                'account',
                'action',
                'activity_log',
                'ai_observability_clusters',
                'customer_analytics',
                'customer_journey',
                'customer_task',
                'dashboard',
                'dashboard_template',
                'data_catalog',
                'dataset',
                'early_access_feature',
                'endpoint',
                'error_tracking',
                'evaluation',
                'experiment',
                'experiment_holdout',
                'experiment_saved_metric',
                'export',
                'external_data_source',
                'feature_flag',
                'heatmap',
                'hog_flow',
                'insight',
                'llm_analytics',
                'llm_playground',
                'llm_prompt',
                'llm_provider_key',
                'llm_skill',
                'logs',
                'marketing_analytics',
                'mcp_analytics',
                'metrics',
                'notebook',
                'project',
                'property_definition',
                'replay_scanner',
                'revenue_analytics',
                'session_recording',
                'session_recording_playlist',
                'sharing_configuration',
                'stamphog',
                'survey',
                'tagger',
                'ticket',
                'toolbar',
                'tracing',
                'vision_alert',
                'warehouse_objects',
                'warehouse_table',
                'warehouse_view',
                'web_analytics',
            ])
            .describe(
                '\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            )
            .describe(
                'The scope of the rule: `project` for the project itself, a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.\n\n\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            ),
        resource_id: zod
            .string()
            .nullish()
            .describe(
                "The object the rule applies to: an object's primary key, or a property definition id when `resource` is `property_definition`. Omit it for a rule on the whole resource type or on the project."
            ),
        access_level: zod
            .string()
            .nullable()
            .describe(
                'The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.'
            ),
        role_id: zod.uuid().describe('The role id, as `role_id` in the roles endpoint.'),
    })
    .describe('A rule for every member of one role.')

/**
 * Create or update a property access control rule.
 */
export const PropertyAccessControlsCreateBody = /* @__PURE__ */ zod
    .object({
        property_definition_id: zod.string().describe('The property definition ID this rule applies to.'),
        access_level: zod
            .enum(['read_write', 'read', 'none'])
            .describe('\* `read_write` - read_write\n\* `read` - read\n\* `none` - none')
            .describe(
                'The access level to set for this rule.\n\n\* `read_write` - read_write\n\* `read` - read\n\* `none` - none'
            ),
        organization_member: zod.uuid().nullish().describe('The organization member UUID to set an override for.'),
        role: zod.uuid().nullish().describe('The role UUID to set an override for.'),
    })
    .describe('Request body for upserting a rule (create or update).')
