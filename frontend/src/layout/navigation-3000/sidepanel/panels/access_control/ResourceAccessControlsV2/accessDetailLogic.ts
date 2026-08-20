import { MakeLogicType, actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { APIScopeObject, AccessControlLevel, InsightShortId } from '~/types'

import {
    propertyAccessControlsCreate,
    propertyAccessControlsDestroy,
} from 'products/access_control/frontend/generated/api'
import { AccessLevelEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import type { ScopeType } from './types'

/** A member or role whose access detail panel is open. The 'default' scope has no panel of its own. */
export type AccessDetailSubjectScope = Exclude<ScopeType, 'default'>

export interface AccessObjectRule {
    resource: APIScopeObject
    resource_id: string
    name: string
    /** Insights link by short_id rather than resource_id; null for other resources. */
    short_id: string | null
    access_level: AccessControlLevel
}

export interface AccessPropertyRule {
    property_definition_id: string
    property: string
    property_type: 'person' | 'event'
    access_level: AccessLevelEnumApi
}

export interface AccessDetailLogicProps {
    projectId: string
    scopeType: ScopeType
    subjectId: string
}

export interface AccessDetailSubject {
    scopeType: AccessDetailSubjectScope
    subjectId: string
}

/** Parses the side panel's `member:<id>` / `role:<id>` options, used for deep links into the panel. */
export function parseAccessDetailOptions(options: string | null): AccessDetailSubject | null {
    const [scope, subjectId] = (options ?? '').split(':')
    if (!subjectId) {
        return null
    }
    return { scopeType: scope === 'role' ? 'role' : 'member', subjectId }
}

interface ObjectRuleResourceConfig {
    /** A link to open the object from a stored rule, for types addressable from it. */
    url: (rule: AccessObjectRule) => string | null
    /**
     * The inverse: pull the object's lookup id out of a pasted app path, so the picker can resolve
     * a URL. Receives the pathname with any /project/<id> prefix stripped. Insights yield the
     * short_id; the search endpoint accepts it and returns the pk rules store.
     */
    parseUrl?: (path: string) => string | null
}

/**
 * Frontend-only presentation extras per resource type: how a rule links to its object, and how a
 * pasted URL resolves back to one. Which resources exist at all — in the picker and the rules
 * list — comes entirely from the backend (`object_rule_resources` on the defaults endpoint,
 * derived from viewset registration), so a type missing here is fully usable, just without
 * links or URL paste.
 */
export const OBJECT_RULE_RESOURCE_CONFIG: Partial<Record<APIScopeObject, ObjectRuleResourceConfig>> = {
    dashboard: {
        url: (rule) => urls.dashboard(rule.resource_id),
        parseUrl: (path) => /^\/dashboard\/(\d+)(?:[/?#]|$)/.exec(path)?.[1] ?? null,
    },
    insight: {
        url: (rule) => (rule.short_id ? urls.insightView(rule.short_id as InsightShortId) : null),
        parseUrl: (path) => /^\/insights\/([A-Za-z0-9]+)(?:[/?#]|$)/.exec(path)?.[1] ?? null,
    },
    feature_flag: {
        url: (rule) => urls.featureFlag(rule.resource_id),
        parseUrl: (path) => /^\/feature_flags\/(\d+)(?:[/?#]|$)/.exec(path)?.[1] ?? null,
    },
    experiment: {
        url: (rule) => urls.experiment(rule.resource_id),
        parseUrl: (path) => /^\/experiments\/(\d+)(?:[/?#]|$)/.exec(path)?.[1] ?? null,
    },
    survey: {
        url: (rule) => urls.survey(rule.resource_id),
        parseUrl: (path) => /^\/surveys\/([0-9a-f-]{36})(?:[/?#]|$)/.exec(path)?.[1] ?? null,
    },
    // The warehouse pair opens through SQL editor deep links whose object reference lives in
    // query params, so there is nothing to parse back out of a pathname
    warehouse_table: {
        url: (rule) => urls.sqlEditor({ query: `SELECT * FROM ${rule.name} LIMIT 100` }),
    },
    warehouse_view: { url: (rule) => urls.sqlEditor({ view_id: rule.resource_id }) },
    action: {
        url: (rule) => urls.action(rule.resource_id),
        parseUrl: (path) => /^\/data-management\/actions\/(\d+)(?:[/?#]|$)/.exec(path)?.[1] ?? null,
    },
    external_data_source: {
        url: (rule) => urls.dataWarehouseSource(`managed-${rule.resource_id}`),
        parseUrl: (path) => /^\/data-management\/sources\/managed-([0-9a-f-]{36})(?:[/?#]|$)/.exec(path)?.[1] ?? null,
    },
}

/** A link to open the object, null for types we can't address (e.g. notebooks need a short_id). */
export function objectRuleUrl(rule: AccessObjectRule): string | null {
    return OBJECT_RULE_RESOURCE_CONFIG[rule.resource]?.url(rule) ?? null
}

/** Matches a pasted app URL to a resource and lookup id, or null when it isn't one of ours. */
export function parseObjectRuleUrl(input: string): { resource: APIScopeObject; id: string } | null {
    const trimmed = input.trim()
    if (!trimmed.startsWith('http') && !trimmed.startsWith('/')) {
        return null
    }
    let pathname: string
    try {
        pathname = trimmed.startsWith('http') ? new URL(trimmed).pathname : trimmed.split(/[?#]/)[0]
    } catch {
        return null
    }
    const path = pathname.replace(/^\/project\/\d+/, '')
    for (const [resource, config] of Object.entries(OBJECT_RULE_RESOURCE_CONFIG)) {
        const id = config.parseUrl?.(path)
        if (id) {
            return { resource: resource as APIScopeObject, id }
        }
    }
    return null
}

function subjectRulesEndpoint(props: AccessDetailLogicProps, kind: 'objects' | 'properties'): string {
    const base = `api/projects/${props.projectId}`
    if (props.scopeType === 'default') {
        return `${base}/access_control_default_${kind}`
    }
    if (props.scopeType === 'role') {
        return `${base}/access_control_role_${kind}?role_id=${props.subjectId}`
    }
    return `${base}/access_control_member_${kind}?member_id=${props.subjectId}`
}

// The access-control write APIs target an org member or a role. Sending neither writes the
// project-wide rule, which is what the defaults scope wants.
function subjectBody(props: AccessDetailLogicProps): Record<string, string> {
    if (props.scopeType === 'default') {
        return {}
    }
    return props.scopeType === 'role' ? { role: props.subjectId } : { organization_member: props.subjectId }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accessDetailLogicValues {
    objects: AccessObjectRule[]
    objectsLoading: boolean
    properties: AccessPropertyRule[]
    propertiesLoading: boolean
    ruleSaving: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accessDetailLogicActions {
    loadObjects: () => any
    loadObjectsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadObjectsSuccess: (
        objects: AccessObjectRule[],
        payload?: any
    ) => {
        objects: AccessObjectRule[]
        payload?: any
    }
    loadProperties: () => any
    loadPropertiesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPropertiesSuccess: (
        properties: AccessPropertyRule[],
        payload?: any
    ) => {
        properties: AccessPropertyRule[]
        payload?: any
    }
    ruleSaveFinished: () => {
        value: true
    }
    setObjectRule: (
        resource: APIScopeObject,
        resourceId: string,
        level: AccessControlLevel | null
    ) => {
        level: AccessControlLevel | null
        resource:
            | 'access_control'
            | 'account'
            | 'action'
            | 'activity_log'
            | 'ai_observability_clusters'
            | 'alert'
            | 'annotation'
            | 'approvals'
            | 'batch_export'
            | 'batch_import'
            | 'batch_import_support'
            | 'billing'
            | 'business_knowledge'
            | 'canvas'
            | 'clickhouse_test_cluster_perf'
            | 'cohort'
            | 'comment'
            | 'conversation'
            | 'customer_analytics'
            | 'customer_journey'
            | 'customer_profile_config'
            | 'dashboard'
            | 'dashboard_template'
            | 'data_catalog'
            | 'data_catalog_approval'
            | 'dataset'
            | 'early_access_feature'
            | 'element'
            | 'endpoint'
            | 'engineering_analytics'
            | 'error_tracking'
            | 'evaluation'
            | 'event_definition'
            | 'event_filter'
            | 'experiment'
            | 'experiment_holdout'
            | 'experiment_saved_metric'
            | 'export'
            | 'external_data_schema'
            | 'external_data_source'
            | 'feature_flag'
            | 'field_note'
            | 'file_system'
            | 'file_system_shortcut'
            | 'group'
            | 'health_issue'
            | 'heatmap'
            | 'hog_flow'
            | 'hog_function'
            | 'ingestion_warning'
            | 'insight'
            | 'insight_variable'
            | 'integration'
            | 'internal_run'
            | 'legal_document'
            | 'link'
            | 'live_debugger'
            | 'llm_analytics'
            | 'llm_gateway'
            | 'llm_playground'
            | 'llm_prompt'
            | 'llm_provider_key'
            | 'llm_skill'
            | 'logs'
            | 'loop'
            | 'marketing_analytics'
            | 'mcp_analytics'
            | 'mcp_builtin_agent'
            | 'metrics'
            | 'notebook'
            | 'organization'
            | 'organization_integration'
            | 'organization_member'
            | 'person'
            | 'plugin'
            | 'product_enablement'
            | 'product_tour'
            | 'project'
            | 'property_definition'
            | 'query'
            | 'query_performance'
            | 'replay_scanner'
            | 'revenue_analytics'
            | 'review_hog'
            | 'session_recording'
            | 'session_recording_playlist'
            | 'sharing_configuration'
            | 'signal_scout'
            | 'signal_scout_internal'
            | 'signal_scout_report'
            | 'stamphog'
            | 'streamlit_app'
            | 'subscription'
            | 'survey'
            | 'tagger'
            | 'task'
            | 'ticket'
            | 'toolbar'
            | 'tracing'
            | 'uploaded_media'
            | 'usage_metric'
            | 'user'
            | 'user_interview'
            | 'vision_action'
            | 'visual_review'
            | 'warehouse_objects'
            | 'warehouse_table'
            | 'warehouse_view'
            | 'web_analytics'
            | 'webhook'
            | 'wizard_session'
        resourceId: string
    }
    setPropertyRule: (
        propertyDefinitionId: string,
        level: AccessLevelEnumApi | null
    ) => {
        level: AccessLevelEnumApi | null
        propertyDefinitionId: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accessDetailLogicMeta {
    key: string
}

export type accessDetailLogicType = MakeLogicType<
    accessDetailLogicValues,
    accessDetailLogicActions,
    AccessDetailLogicProps,
    accessDetailLogicMeta
>

export const accessDetailLogic = kea<accessDetailLogicType>([
    path((key) => ['scenes', 'access_control', 'accessDetailLogic', key]),
    props({} as AccessDetailLogicProps),
    key((props) => `${props.projectId}:${props.scopeType}:${props.subjectId}`),

    actions({
        setObjectRule: (resource: APIScopeObject, resourceId: string, level: AccessControlLevel | null) => ({
            resource,
            resourceId,
            level,
        }),
        setPropertyRule: (propertyDefinitionId: string, level: AccessLevelEnumApi | null) => ({
            propertyDefinitionId,
            level,
        }),
        ruleSaveFinished: true,
    }),

    reducers({
        // Guards the rule controls against double submission while a save request is in flight
        ruleSaving: [
            false,
            {
                setObjectRule: () => true,
                setPropertyRule: () => true,
                ruleSaveFinished: () => false,
            },
        ],
    }),

    loaders(({ props }) => ({
        objects: [
            [] as AccessObjectRule[],
            {
                loadObjects: async () =>
                    (await api.get<{ results: AccessObjectRule[] }>(subjectRulesEndpoint(props, 'objects'))).results,
            },
        ],
        properties: [
            [] as AccessPropertyRule[],
            {
                loadProperties: async () =>
                    (await api.get<{ results: AccessPropertyRule[] }>(subjectRulesEndpoint(props, 'properties')))
                        .results,
            },
        ],
    })),

    listeners(({ props, actions }) => ({
        setObjectRule: async ({ resource, resourceId, level }) => {
            // A null level clears the subject's rule on the object
            try {
                await api.put(`api/projects/${props.projectId}/access_control_object_rules`, {
                    resource,
                    resource_id: resourceId,
                    ...subjectBody(props),
                    access_level: level,
                })
                lemonToast.success(level === null ? 'Rule removed' : 'Access rule saved')
                actions.loadObjects()
            } catch (e) {
                const error = (e as Record<string, any>).detail || 'Failed to save access rule'
                lemonToast.error(error)
            } finally {
                actions.ruleSaveFinished()
            }
        },
        setPropertyRule: async ({ propertyDefinitionId, level }) => {
            try {
                if (level === null) {
                    await propertyAccessControlsDestroy(props.projectId, {
                        property_definition_id: propertyDefinitionId,
                        ...subjectBody(props),
                    })
                } else {
                    await propertyAccessControlsCreate(props.projectId, {
                        property_definition_id: propertyDefinitionId,
                        access_level: level,
                        ...subjectBody(props),
                    })
                }
                lemonToast.success(level === null ? 'Rule removed' : 'Property rule saved')
                actions.loadProperties()
            } catch (e) {
                const error = (e as Record<string, any>).detail || 'Failed to save property rule'
                lemonToast.error(error)
            } finally {
                actions.ruleSaveFinished()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadObjects()
        actions.loadProperties()
    }),
])
