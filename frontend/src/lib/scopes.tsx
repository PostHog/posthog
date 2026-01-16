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
    { key: 'activity_log', objectName: 'Activity log', objectPlural: 'activity logs' },
    { key: 'alert', objectName: 'Alert', objectPlural: 'alerts' },
    { key: 'annotation', objectName: 'Annotation', objectPlural: 'annotations' },
    { key: 'batch_export', objectName: 'Batch export', objectPlural: 'batch exports' },
    { key: 'cohort', objectName: 'Cohort', objectPlural: 'cohorts' },
    { key: 'dashboard', objectName: 'Dashboard', objectPlural: 'dashboards' },
    { key: 'dashboard_template', objectName: 'Dashboard template', objectPlural: 'dashboard templates' },
    { key: 'dataset', objectName: 'Dataset', objectPlural: 'datasets' },
    { key: 'desktop_recording', objectName: 'Desktop recording', objectPlural: 'desktop recordings' },
    { key: 'early_access_feature', objectName: 'Early access feature', objectPlural: 'early access features' },
    { key: 'endpoint', objectName: 'Endpoint', objectPlural: 'endpoints' },
    { key: 'event_definition', objectName: 'Event definition', objectPlural: 'event definitions' },
    { key: 'error_tracking', objectName: 'Error tracking', objectPlural: 'error tracking' },
    { key: 'experiment', objectName: 'Experiment', objectPlural: 'experiments' },
    { key: 'experiment_saved_metric', objectName: 'Shared metric', objectPlural: 'shared metrics' },
    { key: 'export', objectName: 'Export', objectPlural: 'exports' },
    { key: 'feature_flag', objectName: 'Feature flag', objectPlural: 'feature flags' },
    { key: 'group', objectName: 'Group', objectPlural: 'groups' },
    { key: 'hog_function', objectName: 'Hog function', objectPlural: 'hog functions' },
    { key: 'insight', objectName: 'Insight', objectPlural: 'insights' },
    { key: 'insight_variable', objectName: 'Insight variable', objectPlural: 'insight variables' },
    { key: 'integration', objectName: 'Integration', objectPlural: 'integrations', disabledActions: ['write'] },
    { key: 'llm_gateway', objectName: 'LLM gateway', objectPlural: 'LLM gateway', disabledActions: ['write'] },
    { key: 'llm_prompt', objectName: 'LLM prompt', objectPlural: 'LLM prompts' },
    { key: 'logs', objectName: 'Logs', objectPlural: 'logs' },
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
    { key: 'session_recording', objectName: 'Session recording', objectPlural: 'session recordings' },
    {
        key: 'session_recording_playlist',
        objectName: 'Session recording playlist',
        objectPlural: 'session recording playlists',
    },
    { key: 'sharing_configuration', objectName: 'Sharing configuration', objectPlural: 'sharing configurations' },
    { key: 'subscription', objectName: 'Subscription', objectPlural: 'subscriptions' },
    { key: 'survey', objectName: 'Survey', objectPlural: 'surveys' },
    { key: 'ticket', objectName: 'Ticket', objectPlural: 'tickets' },
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
    { key: 'task', objectName: 'Task', objectPlural: 'tasks' },
    {
        key: 'webhook',
        objectName: 'Webhook',
        objectPlural: 'webhooks',
        info: 'Webhook configuration is currently only enabled for the Zapier integration.',
    },
    { key: 'warehouse_view', objectName: 'Warehouse view', objectPlural: 'warehouse views' },
    { key: 'warehouse_table', objectName: 'Warehouse table', objectPlural: 'warehouse tables' },
]

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
        scopes: API_SCOPES.filter(({ key }) => !key.includes('llm_gateway')).map(({ key }) =>
            ['feature_flag', 'insight', 'dashboard', 'survey', 'experiment'].includes(key)
                ? `${key}:write`
                : `${key}:read`
        ),
        access_type: 'all',
    },
    { value: 'all_access', label: 'All access', scopes: ['*'] },
]

export const APIScopeActionLabels: Record<APIScopeAction, string> = {
    read: 'Read',
    write: 'Write',
}

export const DEFAULT_OAUTH_SCOPES = ['openid', 'email', 'profile']

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
        return undefined
    }

    const [object, action] = scope.split(':')

    if (!object || !action) {
        return scope
    }

    const scopeObject = API_SCOPES.find((s) => s.key === object)
    const actionWord = action === 'write' ? 'Write' : 'Read'

    return `${actionWord} access to ${scopeObject?.objectPlural ?? scope}`
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
