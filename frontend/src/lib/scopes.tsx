import { AGENT_USE_CASE_SCOPES } from 'lib/agentScopes.generated'

import type { APIScopeAction, APIScopeObject } from '~/types'

export const MAX_API_KEYS_PER_USER = 10 // Same as in posthog/api/personal_api_key.py

export type APIScope = {
    key: APIScopeObject
    objectName: string
    objectPlural: string
    info?: string | JSX.Element
    disabledActions?: ('read' | 'write')[]
    disabledWhenProjectScoped?: boolean
    description?: string
    warnings?: Partial<Record<'read' | 'write', string | JSX.Element>>
}

export const API_SCOPES: APIScope[] = [
    { key: 'action', objectName: 'Action', objectPlural: 'actions' },
    { key: 'access_control', objectName: 'Access control', objectPlural: 'access controls' },
    { key: 'account', objectName: 'Account', objectPlural: 'accounts' },
    { key: 'activity_log', objectName: 'Activity log', objectPlural: 'activity logs' },
    { key: 'agents', objectName: 'Agent', objectPlural: 'agents' },
    {
        key: 'agent_approvals',
        objectName: 'Agent approval',
        objectPlural: 'agent approvals',
        info: 'Grants the ability to approve or reject queued agent tool-approval requests on behalf of the consenting user, including requests whose spec sets `allow_agent_approver: false` (human-only). Only grant this to OAuth clients that put a human in the loop at decide time, like the PostHog Code desktop app.',
        disabledActions: ['read'],
    },
    { key: 'alert', objectName: 'Alert', objectPlural: 'alerts' },
    { key: 'annotation', objectName: 'Annotation', objectPlural: 'annotations' },
    { key: 'approvals', objectName: 'Approvals', objectPlural: 'approvals' },
    { key: 'batch_export', objectName: 'Batch export', objectPlural: 'batch exports' },
    { key: 'business_knowledge', objectName: 'Business knowledge', objectPlural: 'business knowledge' },
    // `clickhouse_test_cluster_perf` is omitted — see `INTERNAL_API_SCOPE_OBJECTS` in posthog/scopes.py.
    { key: 'cohort', objectName: 'Cohort', objectPlural: 'cohorts' },
    { key: 'comment', objectName: 'Comment', objectPlural: 'comments' },
    { key: 'customer_analytics', objectName: 'Customer analytics', objectPlural: 'customer analytics' },
    { key: 'customer_journey', objectName: 'Customer journey', objectPlural: 'customer journeys' },
    { key: 'dashboard', objectName: 'Dashboard', objectPlural: 'dashboards' },
    { key: 'dashboard_template', objectName: 'Dashboard template', objectPlural: 'dashboard templates' },
    { key: 'dataset', objectName: 'Dataset', objectPlural: 'datasets' },
    { key: 'early_access_feature', objectName: 'Early access feature', objectPlural: 'early access features' },
    { key: 'element', objectName: 'Element', objectPlural: 'elements' },
    { key: 'endpoint', objectName: 'Endpoint', objectPlural: 'endpoints' },
    { key: 'engineering_analytics', objectName: 'Engineering analytics', objectPlural: 'engineering analytics' },
    { key: 'event_definition', objectName: 'Event definition', objectPlural: 'event definitions' },
    { key: 'error_tracking', objectName: 'Error tracking', objectPlural: 'error tracking' },
    { key: 'evaluation', objectName: 'Evaluation', objectPlural: 'evaluations' },
    { key: 'experiment', objectName: 'Experiment', objectPlural: 'experiments' },
    { key: 'experiment_holdout', objectName: 'Holdout', objectPlural: 'holdouts' },
    { key: 'experiment_saved_metric', objectName: 'Shared metric', objectPlural: 'shared metrics' },
    { key: 'external_data_source', objectName: 'External data source', objectPlural: 'external data sources' },
    { key: 'export', objectName: 'Export', objectPlural: 'exports' },
    { key: 'feature_flag', objectName: 'Feature flag', objectPlural: 'feature flags' },
    {
        key: 'file_system',
        objectName: 'File system',
        objectPlural: 'file system items',
        // Read-only for now: the file-system delete path cascades into the backing
        // object (dashboard, insight, cohort, feature flag, hog function, ...), so a
        // `file_system:write` token would bypass the more specific resource scopes.
        disabledActions: ['write'],
    },
    { key: 'file_system_shortcut', objectName: 'File system shortcut', objectPlural: 'file system shortcuts' },
    { key: 'group', objectName: 'Group', objectPlural: 'groups' },
    { key: 'health_issue', objectName: 'Health issue', objectPlural: 'health issues' },
    { key: 'heatmap', objectName: 'Heatmap', objectPlural: 'heatmaps' },
    { key: 'hog_flow', objectName: 'Workflow', objectPlural: 'workflows' },
    { key: 'hog_function', objectName: 'Hog function', objectPlural: 'hog functions' },
    { key: 'insight', objectName: 'Insight', objectPlural: 'insights' },
    { key: 'insight_variable', objectName: 'Insight variable', objectPlural: 'insight variables' },
    { key: 'integration', objectName: 'Integration', objectPlural: 'integrations', disabledActions: ['write'] },
    { key: 'legal_document', objectName: 'Legal document', objectPlural: 'legal documents' },
    { key: 'live_debugger', objectName: 'Live debugger', objectPlural: 'live debugger' },
    { key: 'llm_analytics', objectName: 'AI observability', objectPlural: 'AI observability' },
    { key: 'llm_gateway', objectName: 'LLM gateway', objectPlural: 'LLM gateway', disabledActions: ['write'] },
    { key: 'llm_prompt', objectName: 'LLM prompt', objectPlural: 'LLM prompts' },
    { key: 'llm_provider_key', objectName: 'LLM provider key', objectPlural: 'LLM provider keys' },
    { key: 'llm_skill', objectName: 'LLM skill', objectPlural: 'LLM skills' },
    { key: 'logs', objectName: 'Logs', objectPlural: 'logs' },
    { key: 'marketing_analytics', objectName: 'Marketing analytics', objectPlural: 'marketing analytics' },
    { key: 'mcp_analytics', objectName: 'MCP analytics', objectPlural: 'MCP analytics' },
    { key: 'metrics', objectName: 'Metrics', objectPlural: 'metrics' },
    { key: 'notebook', objectName: 'Notebook', objectPlural: 'notebooks' },
    { key: 'organization', objectName: 'Organization', objectPlural: 'organizations', disabledWhenProjectScoped: true },
    {
        key: 'organization_integration',
        objectName: 'Organization integration',
        objectPlural: 'organization integrations',
        disabledWhenProjectScoped: true,
    },
    {
        key: 'organization_member',
        objectName: 'Organization member',
        objectPlural: 'organization members',
        disabledWhenProjectScoped: true,
        warnings: {
            write: (
                <>
                    This scope can be used to invite users to your organization,
                    <br />
                    effectively <strong>allowing access to other scopes via the added user</strong>.
                </>
            ),
        },
    },
    { key: 'person', objectName: 'Person', objectPlural: 'persons' },
    { key: 'customer_profile_config', objectName: 'Customer profile config', objectPlural: 'customer profile configs' },
    { key: 'plugin', objectName: 'Plugin', objectPlural: 'plugins' },
    {
        key: 'product_enablement',
        objectName: 'Product enablement',
        objectPlural: 'product enablement',
        disabledActions: ['read'],
    },
    { key: 'product_tour', objectName: 'Product tour', objectPlural: 'product tours' },
    {
        key: 'project',
        objectName: 'Project',
        objectPlural: 'projects',
        warnings: {
            write: 'This scope can be used to create or modify projects, including settings about how data is ingested.',
        },
    },
    { key: 'property_definition', objectName: 'Property definition', objectPlural: 'property definitions' },
    { key: 'query', objectName: 'Query', objectPlural: 'queries', disabledActions: ['write'] },
    // `query_performance` is omitted — OAuth-hidden, PAT-grantable only (see `OAUTH_HIDDEN_SCOPE_OBJECTS` in posthog/scopes.py).
    // `wizard_session` is also omitted for the same reason.
    { key: 'replay_scanner', objectName: 'Replay scanner', objectPlural: 'replay scanners' },
    { key: 'revenue_analytics', objectName: 'Revenue analytics', objectPlural: 'revenue analytics' },
    { key: 'session_recording', objectName: 'Session recording', objectPlural: 'session recordings' },
    {
        key: 'session_recording_playlist',
        objectName: 'Session recording playlist',
        objectPlural: 'session recording playlists',
    },
    { key: 'sharing_configuration', objectName: 'Sharing configuration', objectPlural: 'sharing configurations' },
    { key: 'subscription', objectName: 'Subscription', objectPlural: 'subscriptions' },
    { key: 'survey', objectName: 'Survey', objectPlural: 'surveys' },
    { key: 'tagger', objectName: 'Tagger', objectPlural: 'taggers' },
    { key: 'ticket', objectName: 'Ticket', objectPlural: 'tickets' },
    { key: 'tracing', objectName: 'Tracing', objectPlural: 'tracing' },
    { key: 'field_note', objectName: 'Field note', objectPlural: 'field notes' },
    { key: 'uploaded_media', objectName: 'Uploaded media', objectPlural: 'uploaded media' },
    { key: 'usage_metric', objectName: 'Usage metric', objectPlural: 'usage metrics' },
    {
        key: 'user',
        objectName: 'User',
        objectPlural: 'users',
        disabledActions: ['write'],
        warnings: {
            read: (
                <>
                    This scope allows you to retrieve your own user object.
                    <br />
                    Note that the user object <strong>lists all organizations and projects you're in</strong>.
                </>
            ),
        },
    },
    { key: 'signal_scout', objectName: 'Signals agent', objectPlural: 'signals agents' },
    { key: 'task', objectName: 'Task', objectPlural: 'tasks' },
    { key: 'user_interview', objectName: 'User interview', objectPlural: 'user interviews' },
    { key: 'visual_review', objectName: 'Visual review', objectPlural: 'visual reviews' },
    {
        key: 'webhook',
        objectName: 'Webhook',
        objectPlural: 'webhooks',
        info: 'Webhook configuration is currently only enabled for the Zapier integration.',
    },
    { key: 'warehouse_view', objectName: 'Warehouse view', objectPlural: 'warehouse views' },
    { key: 'warehouse_table', objectName: 'Warehouse table', objectPlural: 'warehouse tables' },
    { key: 'web_analytics', objectName: 'Web analytics', objectPlural: 'web analytics' },
]
API_SCOPES.sort((a, b) => a.objectName.localeCompare(b.objectName))

export const PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION = ['endpoint:read', 'feature_flag:read'] as const

export type ProjectSecretAPIKeyAllowedScope = (typeof PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION)[number]

const API_KEY_CREATION_ACTIONS = ['read', 'write'] as const

// Scopes the manual key-creation UI can render and submit. This excludes actions
// disabled for Personal API Keys and any generated scope whose object has no UI row.
const API_KEY_CREATION_RENDERABLE_SCOPES = new Set(
    API_SCOPES.flatMap(({ key, disabledActions }) =>
        API_KEY_CREATION_ACTIONS.filter((action) => !disabledActions?.includes(action)).map(
            (action) => `${key}:${action}`
        )
    )
)

// Actions the manual key-creation UI withholds from Personal API Keys
// (e.g. file_system:write, integration:write, user:write) — see `disabledActions`
// above.
export const API_KEY_CREATION_DISABLED_SCOPES = new Set(
    API_SCOPES.flatMap(({ key, disabledActions }) => (disabledActions ?? []).map((action) => `${key}:${action}`))
)

export const AGENT_CLI_API_KEY_SCOPES = AGENT_USE_CASE_SCOPES.filter((scope) =>
    API_KEY_CREATION_RENDERABLE_SCOPES.has(scope)
)

export const API_KEY_SCOPE_PRESETS: {
    value: string
    label: string
    scopes: string[]
    access_type?: 'all' | 'organizations' | 'teams'
    isCloudOnly?: boolean
}[] = [
    { value: 'local_evaluation', label: 'Local feature flag evaluation', scopes: ['feature_flag:read'] },
    {
        value: 'source_map_upload',
        label: 'Source map upload',
        scopes: ['organization:read', 'error_tracking:write'],
    },
    {
        value: 'zapier',
        label: 'Zapier integration',
        scopes: ['action:read', 'query:read', 'project:read', 'organization:read', 'user:read', 'webhook:write'],
    },
    {
        value: 'n8n',
        label: 'n8n integration',
        scopes: ['action:read', 'query:read', 'project:read', 'organization:read', 'user:read', 'webhook:write'],
    },
    { value: 'analytics', label: 'Performing analytics queries', scopes: ['query:read'] },
    { value: 'endpoints', label: 'Endpoint execution', scopes: ['endpoint:read'] },
    {
        value: 'project_management',
        label: 'Project & user management',
        scopes: ['project:write', 'organization:read', 'organization_member:write'],
    },
    {
        value: 'mcp_server',
        label: 'MCP Server',
        scopes: API_SCOPES.filter(({ key }) => !key.includes('llm_gateway') && !key.includes('file_system')).map(
            ({ key }) => `${key}:write`
        ),
        access_type: 'all',
    },
    {
        value: 'agent_cli',
        label: 'Agent CLI',
        scopes: AGENT_CLI_API_KEY_SCOPES,
        access_type: 'all',
    },
    {
        value: 'read_only_access',
        label: 'Read-only access',
        scopes: API_SCOPES.map(({ key }) => `${key}:read`),
    },
    { value: 'all_access', label: 'All access', scopes: ['*'] },
]

export const APIScopeActionLabels: Record<APIScopeAction, string> = {
    read: 'Read',
    write: 'Write',
}

export type ProjectSecretAPIKeyScopePreset = {
    value: string
    label: string
    scopes: string[]
    isCloudOnly?: boolean
}

export const PROJECT_SECRET_API_KEY_SCOPE_PRESETS: ProjectSecretAPIKeyScopePreset[] = [
    { value: 'endpoint_execution', label: 'Endpoint execution', scopes: ['endpoint:read'] },
    { value: 'local_evaluation', label: 'Local feature flag evaluation', scopes: ['feature_flag:read'] },
    { value: 'llm_gateway', label: 'AI gateway access', scopes: ['llm_gateway:read'] },
]

export const DEFAULT_OAUTH_SCOPES = ['openid', 'email', 'profile']

// Scopes required by the PostHog MCP server (https://mcp.posthog.com)
// These match the scopes_supported in the MCP server's OAuth protected resource metadata
export const MCP_SERVER_OAUTH_SCOPES = [
    'openid',
    'profile',
    'email',
    'introspection',
    'user:read',
    'user:write',
    'organization:read',
    'project:read',
    'project:write',
    'feature_flag:read',
    'feature_flag:write',
    'experiment:read',
    'experiment:write',
    'insight:read',
    'insight:write',
    'dashboard:read',
    'dashboard:write',
    'query:read',
    'survey:read',
    'survey:write',
    'event_definition:read',
    'event_definition:write',
    'error_tracking:read',
    'logs:read',
    'tracing:read',
]

export const getScopeDescription = (scope: string): string | undefined => {
    if (scope === '*') {
        return 'Read and write access to all PostHog data'
    }

    if (scope === 'openid') {
        return 'View your User ID'
    }

    if (scope === 'email') {
        return 'View your email address'
    }

    if (scope === 'profile') {
        return 'View basic user account information'
    }

    if (scope === 'introspection') {
        // OAuth-internal scope — never shown to users; list call sites .filter(Boolean) it out.
        return undefined
    }

    const [object, action] = scope.split(':')

    if (!object || !action) {
        return scope
    }

    const actionWord = action === 'write' ? 'Write' : 'Read'

    const scopeObject = API_SCOPES.find((s) => s.key === object)
    if (!scopeObject) {
        // OAuth-hidden scope (e.g. wizard_session, query_performance) — absent from API_SCOPES,
        // so derive a readable label from the raw key rather than surfacing the raw identifier.
        return `${actionWord} access to ${object.replace(/_/g, ' ')}`
    }

    return `${actionWord} access to ${scopeObject.objectPlural}`
}

export const getMinimumEquivalentScopes = (scopes: string[]): string[] => {
    if (scopes.includes('*')) {
        return ['*']
    }

    const highestScopes: Record<string, string> = {}

    for (const scope of scopes) {
        if (['openid', 'email', 'profile'].includes(scope)) {
            highestScopes[scope] = 'default'
            continue
        }

        const [object, action] = scope.split(':')
        if (!object || !action) {
            continue
        }
        if (!highestScopes[object] || (action === 'write' && highestScopes[object] === 'read')) {
            highestScopes[object] = action
        }
    }

    return Object.entries(highestScopes).map(([object, action]) => {
        if (action === 'default') {
            return object
        }
        return `${object}:${action}`
    })
}

/** Convert scopes array format to object format for easier UI manipulation */
export const scopesArrayToObject = (scopes: string[]): Record<string, string> => {
    const result: Record<string, string> = {}
    scopes.forEach((scope) => {
        const [key, action] = scope.split(':')
        if (key && action) {
            result[key] = action
        }
    })
    return result
}

/** Convert scopes object format back to array format for API submission */
export const scopesObjectToArray = (scopesObj: Record<string, string>): string[] => {
    return Object.entries(scopesObj).map(([key, action]) => `${key}:${action}`)
}
