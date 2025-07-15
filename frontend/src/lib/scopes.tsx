import type { APIScopeAction, APIScopeObject } from '~/types'

export const MAX_API_KEYS_PER_USER = 10 // Same as in posthog/api/personal_api_key.py

export type APIScope = {
    key: APIScopeObject
    info?: string | JSX.Element
    disabledActions?: ('read' | 'write')[]
    disabledWhenProjectScoped?: boolean
    description?: string
    warnings?: Partial<Record<'read' | 'write', string | JSX.Element>>
    objectPlural: string
}

export const API_SCOPES: APIScope[] = [
    { key: 'action', objectPlural: 'actions' },
    { key: 'access_control', objectPlural: 'access controls', disabledActions: ['write'] },
    { key: 'activity_log', objectPlural: 'activity logs' },
    { key: 'annotation', objectPlural: 'annotations' },
    { key: 'batch_export', objectPlural: 'batch exports' },
    { key: 'cohort', objectPlural: 'cohorts' },
    { key: 'dashboard', objectPlural: 'dashboards' },
    { key: 'dashboard_template', objectPlural: 'dashboard templates' },
    { key: 'early_access_feature', objectPlural: 'early access features' },
    { key: 'event_definition', objectPlural: 'event definitions' },
    { key: 'error_tracking', objectPlural: 'error tracking' },
    { key: 'experiment', objectPlural: 'experiments' },
    { key: 'export', objectPlural: 'exports' },
    { key: 'feature_flag', objectPlural: 'feature flags' },
    { key: 'group', objectPlural: 'groups' },
    { key: 'hog_function', objectPlural: 'hog functions' },
    { key: 'insight', objectPlural: 'insights' },
    { key: 'notebook', objectPlural: 'notebooks' },
    { key: 'organization', disabledWhenProjectScoped: true, objectPlural: 'organizations' },
    {
        key: 'organization_member',
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
    { key: 'person', objectPlural: 'persons' },
    { key: 'plugin', objectPlural: 'plugins' },
    {
        key: 'project',
        objectPlural: 'projects',
        warnings: {
            write: 'This scope can be used to create or modify projects, including settings about how data is ingested.',
        },
    },
    { key: 'property_definition', objectPlural: 'property definitions' },
    { key: 'query', disabledActions: ['write'], objectPlural: 'queries' },
    { key: 'session_recording', objectPlural: 'session recordings' },
    { key: 'session_recording_playlist', objectPlural: 'session recording playlists' },
    { key: 'sharing_configuration', objectPlural: 'sharing configurations' },
    { key: 'subscription', objectPlural: 'subscriptions' },
    { key: 'survey', objectPlural: 'surveys' },
    {
        key: 'user',
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
    {
        key: 'webhook',
        info: 'Webhook configuration is currently only enabled for the Zapier integration.',
        objectPlural: 'webhooks',
    },
    { key: 'warehouse_view', objectPlural: 'warehouse views' },
    { key: 'warehouse_table', objectPlural: 'warehouse tables' },
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
        value: 'zapier',
        label: 'Zapier integration',
        scopes: ['action:read', 'query:read', 'project:read', 'organization:read', 'user:read', 'webhook:write'],
    },
    { value: 'analytics', label: 'Performing analytics queries', scopes: ['query:read'] },
    {
        value: 'project_management',
        label: 'Project & user management',
        scopes: ['project:write', 'organization:read', 'organization_member:write'],
    },
    {
        value: 'mcp_server',
        label: 'MCP Server',
        scopes: API_SCOPES.map(({ key }) =>
            ['feature_flag', 'insight'].includes(key) ? `${key}:write` : `${key}:read`
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

export const getScopeDescription = (scope: string): string => {
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
