import type { APIScopeAction, APIScopeObject } from '~/types'

export const MAX_API_KEYS_PER_USER = 10 // Same as in posthog/api/personal_api_key.py

export type APIScope = {
    key: APIScopeObject
    info?: string | JSX.Element
    disabledActions?: ('read' | 'write')[]
    disabledWhenProjectScoped?: boolean
    description?: string
    warnings?: Partial<Record<'read' | 'write', string | JSX.Element>>
}

export const APIScopes: APIScope[] = [
    { key: 'action' },
    { key: 'activity_log' },
    { key: 'annotation' },
    { key: 'batch_export' },
    { key: 'cohort' },
    { key: 'dashboard' },
    { key: 'dashboard_template' },
    { key: 'early_access_feature' },
    { key: 'event_definition' },
    { key: 'error_tracking' },
    { key: 'experiment' },
    { key: 'export' },
    { key: 'feature_flag' },
    { key: 'group' },
    { key: 'hog_function' },
    { key: 'insight' },
    { key: 'notebook' },
    { key: 'organization', disabledWhenProjectScoped: true },
    {
        key: 'organization_member',
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
    { key: 'person' },
    { key: 'plugin' },
    {
        key: 'project',
        warnings: {
            write: 'This scope can be used to create or modify projects, including settings about how data is ingested.',
        },
    },
    { key: 'property_definition' },
    { key: 'query', disabledActions: ['write'] },
    { key: 'session_recording' },
    { key: 'session_recording_playlist' },
    { key: 'sharing_configuration' },
    { key: 'subscription' },
    { key: 'survey' },
    {
        key: 'user',
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
    { key: 'webhook', info: 'Webhook configuration is currently only enabled for the Zapier integration.' },
    { key: 'warehouse_view' },
    { key: 'warehouse_table' },
]

export const API_KEY_SCOPE_PRESETS: { value: string; label: string; scopes: string[]; isCloudOnly?: boolean }[] = [
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
        scopes: APIScopes.map(({ key }) =>
            ['feature_flag', 'insight'].includes(key) ? `${key}:write` : `${key}:read`
        ),
    },
    { value: 'all_access', label: 'All access', scopes: ['*'] },
]

export const APIScopeActionLabels: Record<APIScopeAction, string> = {
    read: 'Read',
    write: 'Write',
}

export const DEFAULT_OAUTH_SCOPES = ['openid']

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

    const scopeObject = APIScopes.find((s) => s.key === object)
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
