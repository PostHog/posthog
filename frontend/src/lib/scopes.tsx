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

export type APIScopeGroup = {
    key: string
    label: string
    scopes: APIScopeObject[]
}

export type APIKeyIntentTile = {
    key: string
    title: string
    description: string
    icon: string
    scopes: string[]
}

export const API_SCOPES: APIScope[] = [
    {
        key: 'action',
        objectName: 'Action',
        objectPlural: 'actions',
        description: 'Custom events defined by rules on ingested events',
    },
    {
        key: 'access_control',
        objectName: 'Access control',
        objectPlural: 'access controls',
        description: 'Role-based access permissions for resources',
    },
    {
        key: 'activity_log',
        objectName: 'Activity log',
        objectPlural: 'activity logs',
        description: 'Audit trail of changes made by team members',
    },
    {
        key: 'alert',
        objectName: 'Alert',
        objectPlural: 'alerts',
        description: 'Notifications triggered by insight threshold changes',
    },
    {
        key: 'annotation',
        objectName: 'Annotation',
        objectPlural: 'annotations',
        description: 'Notes attached to specific dates on insights',
    },
    {
        key: 'batch_export',
        objectName: 'Batch export',
        objectPlural: 'batch exports',
        description: 'Scheduled bulk data exports to external destinations',
    },
    {
        key: 'cohort',
        objectName: 'Cohort',
        objectPlural: 'cohorts',
        description: 'Reusable groups of users based on properties or behavior',
    },
    {
        key: 'dashboard',
        objectName: 'Dashboard',
        objectPlural: 'dashboards',
        description: 'Collections of insights and visualizations',
    },
    {
        key: 'dashboard_template',
        objectName: 'Dashboard template',
        objectPlural: 'dashboard templates',
        description: 'Pre-built dashboard layouts for common use cases',
    },
    {
        key: 'dataset',
        objectName: 'Dataset',
        objectPlural: 'datasets',
        description: 'Data warehouse datasets for custom queries',
    },
    {
        key: 'desktop_recording',
        objectName: 'Desktop recording',
        objectPlural: 'desktop recordings',
        description: 'Screen recordings from desktop applications',
    },
    {
        key: 'early_access_feature',
        objectName: 'Early access feature',
        objectPlural: 'early access features',
        description: 'Opt-in features users can self-enroll into',
    },
    {
        key: 'element',
        objectName: 'Element',
        objectPlural: 'elements',
        description: 'Autocaptured DOM elements from your application',
    },
    {
        key: 'endpoint',
        objectName: 'Endpoint',
        objectPlural: 'endpoints',
        description: 'SQL and insight query endpoints for external consumption',
    },
    {
        key: 'event_definition',
        objectName: 'Event definition',
        objectPlural: 'event definitions',
        description: 'Metadata and descriptions for tracked events',
    },
    {
        key: 'error_tracking',
        objectName: 'Error tracking',
        objectPlural: 'error tracking',
        description: 'Captured exceptions and stack traces',
    },
    {
        key: 'experiment',
        objectName: 'Experiment',
        objectPlural: 'experiments',
        description: 'A/B tests and multivariate experiments',
    },
    {
        key: 'experiment_saved_metric',
        objectName: 'Shared metric',
        objectPlural: 'shared metrics',
        description: 'Reusable metrics shared across experiments',
    },
    {
        key: 'external_data_source',
        objectName: 'External data source',
        objectPlural: 'external data sources',
        description: 'Connections to external databases like Postgres or Stripe',
    },
    {
        key: 'export',
        objectName: 'Export',
        objectPlural: 'exports',
        description: 'One-off data exports from insights or lists',
    },
    {
        key: 'feature_flag',
        objectName: 'Feature flag',
        objectPlural: 'feature flags',
        description: 'Toggle features on/off for users and groups',
    },
    {
        key: 'group',
        objectName: 'Group',
        objectPlural: 'groups',
        description: 'Group analytics entities like companies or teams',
    },
    {
        key: 'health_issue',
        objectName: 'Health issue',
        objectPlural: 'health issues',
        description: 'System health checks and data pipeline issues',
    },
    {
        key: 'heatmap',
        objectName: 'Heatmap',
        objectPlural: 'heatmaps',
        description: 'Click and scroll heatmaps for your application',
    },
    {
        key: 'hog_flow',
        objectName: 'Workflow',
        objectPlural: 'workflows',
        description: 'Visual automation workflows built with Hog',
    },
    {
        key: 'hog_function',
        objectName: 'Hog function',
        objectPlural: 'hog functions',
        description: 'Custom functions and destinations written in Hog',
    },
    {
        key: 'insight',
        objectName: 'Insight',
        objectPlural: 'insights',
        description: 'Saved analytics queries and visualizations',
    },
    {
        key: 'insight_variable',
        objectName: 'Insight variable',
        objectPlural: 'insight variables',
        description: 'Reusable filter variables for insights',
    },
    {
        key: 'integration',
        objectName: 'Integration',
        objectPlural: 'integrations',
        disabledActions: ['write'],
        description: 'Third-party service connections like Slack',
    },
    {
        key: 'llm_gateway',
        objectName: 'LLM gateway',
        objectPlural: 'LLM gateway',
        disabledActions: ['write'],
        description: 'Proxy for LLM API calls with cost tracking',
    },
    {
        key: 'llm_prompt',
        objectName: 'LLM prompt',
        objectPlural: 'LLM prompts',
        description: 'Managed prompt templates for LLM applications',
    },
    { key: 'logs', objectName: 'Logs', objectPlural: 'logs', description: 'Application and pipeline log entries' },
    {
        key: 'notebook',
        objectName: 'Notebook',
        objectPlural: 'notebooks',
        description: 'Collaborative documents combining text and analytics',
    },
    {
        key: 'organization',
        objectName: 'Organization',
        objectPlural: 'organizations',
        disabledWhenProjectScoped: true,
        description: 'Organization settings and metadata',
    },
    {
        key: 'organization_integration',
        objectName: 'Organization integration',
        objectPlural: 'organization integrations',
        disabledWhenProjectScoped: true,
        description: 'Organization-level service integrations',
    },
    {
        key: 'organization_member',
        objectName: 'Organization member',
        objectPlural: 'organization members',
        disabledWhenProjectScoped: true,
        description: 'Members and their roles within the organization',
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
    {
        key: 'person',
        objectName: 'Person',
        objectPlural: 'persons',
        description: 'Identified users and their properties',
    },
    {
        key: 'customer_profile_config',
        objectName: 'Customer profile config',
        objectPlural: 'customer profile configs',
        description: 'Configuration for customer profile views',
    },
    {
        key: 'plugin',
        objectName: 'Plugin',
        objectPlural: 'plugins',
        description: 'Installed apps that extend PostHog functionality',
    },
    {
        key: 'product_tour',
        objectName: 'Product tour',
        objectPlural: 'product tours',
        description: 'In-app guided tours for user onboarding',
    },
    {
        key: 'project',
        objectName: 'Project',
        objectPlural: 'projects',
        description: 'Project configuration and data ingestion settings',
        warnings: {
            write: 'This scope can be used to create or modify projects, including settings about how data is ingested.',
        },
    },
    {
        key: 'property_definition',
        objectName: 'Property definition',
        objectPlural: 'property definitions',
        description: 'Metadata and types for event and person properties',
    },
    {
        key: 'query',
        objectName: 'Query',
        objectPlural: 'queries',
        disabledActions: ['write'],
        description: 'Run analytics queries via the API',
    },
    {
        key: 'session_recording',
        objectName: 'Session recording',
        objectPlural: 'session recordings',
        description: 'Recordings of user sessions for playback',
    },
    {
        key: 'session_recording_playlist',
        objectName: 'Session recording playlist',
        objectPlural: 'session recording playlists',
        description: 'Saved collections of session recordings',
    },
    {
        key: 'sharing_configuration',
        objectName: 'Sharing configuration',
        objectPlural: 'sharing configurations',
        description: 'Public sharing settings for dashboards and insights',
    },
    {
        key: 'subscription',
        objectName: 'Subscription',
        objectPlural: 'subscriptions',
        description: 'Scheduled insight exports to Slack or email',
    },
    {
        key: 'survey',
        objectName: 'Survey',
        objectPlural: 'surveys',
        description: 'In-app surveys and user feedback collection',
    },
    {
        key: 'ticket',
        objectName: 'Ticket',
        objectPlural: 'tickets',
        description: 'Support and issue tickets from error tracking',
    },
    {
        key: 'uploaded_media',
        objectName: 'Uploaded media',
        objectPlural: 'uploaded media',
        description: 'Images and files uploaded for use in notebooks',
    },
    {
        key: 'user',
        objectName: 'User',
        objectPlural: 'users',
        disabledActions: ['write'],
        description: 'Your own user account information',
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
        key: 'task',
        objectName: 'Task',
        objectPlural: 'tasks',
        description: 'Background tasks and their execution status',
    },
    {
        key: 'webhook',
        objectName: 'Webhook',
        objectPlural: 'webhooks',
        description: 'Webhook configuration for the Zapier integration',
        info: 'Webhook configuration is currently only enabled for the Zapier integration.',
    },
    {
        key: 'warehouse_view',
        objectName: 'Warehouse view',
        objectPlural: 'warehouse views',
        description: 'Custom SQL views on warehouse data',
    },
    {
        key: 'warehouse_table',
        objectName: 'Warehouse table',
        objectPlural: 'warehouse tables',
        description: 'Tables synced or created in the data warehouse',
    },
]

// --- Scope groups for the review step ---

export const API_SCOPE_GROUPS: APIScopeGroup[] = [
    {
        key: 'analytics',
        label: 'Analytics & insights',
        scopes: [
            'query',
            'insight',
            'insight_variable',
            'dashboard',
            'dashboard_template',
            'annotation',
            'event_definition',
            'property_definition',
            'cohort',
            'action',
            'endpoint',
        ],
    },
    {
        key: 'feature_management',
        label: 'Feature management',
        scopes: [
            'feature_flag',
            'experiment',
            'experiment_saved_metric',
            'early_access_feature',
            'survey',
            'product_tour',
        ],
    },
    {
        key: 'session_replay',
        label: 'Session replay & heatmaps',
        scopes: ['session_recording', 'session_recording_playlist', 'desktop_recording', 'heatmap'],
    },
    {
        key: 'data_pipeline',
        label: 'Data pipeline & warehouse',
        scopes: ['batch_export', 'dataset', 'external_data_source', 'export', 'warehouse_view', 'warehouse_table'],
    },
    {
        key: 'observability',
        label: 'Error tracking & observability',
        scopes: ['error_tracking', 'health_issue', 'logs', 'alert', 'ticket'],
    },
    {
        key: 'ai',
        label: 'AI / LLM',
        scopes: ['llm_gateway', 'llm_prompt'],
    },
    {
        key: 'automations',
        label: 'Automations & integrations',
        scopes: [
            'hog_function',
            'hog_flow',
            'webhook',
            'integration',
            'organization_integration',
            'plugin',
            'subscription',
        ],
    },
    {
        key: 'people',
        label: 'People & groups',
        scopes: ['person', 'group', 'customer_profile_config', 'element'],
    },
    {
        key: 'admin',
        label: 'Organization & project admin',
        scopes: [
            'organization',
            'organization_member',
            'project',
            'user',
            'access_control',
            'activity_log',
            'sharing_configuration',
        ],
    },
    {
        key: 'other',
        label: 'Other',
        scopes: ['notebook', 'uploaded_media', 'task'],
    },
]

const _scopeToGroupCache: Record<string, string> = {}
for (const group of API_SCOPE_GROUPS) {
    for (const scope of group.scopes) {
        _scopeToGroupCache[scope] = group.key
    }
}

/** Returns the group key for a given scope key, or 'other' if not found */
export const getScopeGroup = (scopeKey: APIScopeObject): string => {
    return _scopeToGroupCache[scopeKey] ?? 'other'
}

// --- Intent tiles for the intent step ---

export const API_KEY_INTENT_TILES: APIKeyIntentTile[] = [
    {
        key: 'read_data',
        title: 'Read my data',
        description: 'Pull analytics into apps, scripts, or dashboards',
        icon: 'IconTrending',
        scopes: [
            'query:read',
            'insight:read',
            'dashboard:read',
            'event_definition:read',
            'property_definition:read',
            'cohort:read',
            'annotation:read',
            'action:read',
            'endpoint:read',
        ],
    },
    {
        key: 'feature_releases',
        title: 'Manage feature releases',
        description: 'Evaluate flags, run experiments, manage surveys',
        icon: 'IconToggle',
        scopes: ['feature_flag:write', 'experiment:write', 'survey:write', 'early_access_feature:write'],
    },
    {
        key: 'integrations',
        title: 'Connect an integration',
        description: 'Wire up Zapier, n8n, webhooks, or automation',
        icon: 'IconPlug',
        scopes: ['webhook:write', 'action:read', 'query:read', 'project:read', 'organization:read', 'user:read'],
    },
    {
        key: 'monitor_debug',
        title: 'Monitor & debug',
        description: 'Track errors, upload source maps, view recordings',
        icon: 'IconBug',
        scopes: ['error_tracking:write', 'session_recording:read', 'logs:read', 'health_issue:read', 'alert:read'],
    },
    {
        key: 'build_ai',
        title: 'Build with AI tools',
        description: 'Connect an MCP server or use LLM features',
        icon: 'IconAI',
        scopes: API_SCOPES.filter(({ key }) => !key.includes('llm_gateway')).map(({ key }) =>
            ['feature_flag', 'insight', 'dashboard', 'survey', 'experiment', 'event_definition'].includes(key)
                ? `${key}:write`
                : `${key}:read`
        ),
    },
    {
        key: 'admin',
        title: 'Administer organization',
        description: 'Manage projects, members, and access',
        icon: 'IconGear',
        scopes: [
            'organization:read',
            'organization_member:write',
            'project:write',
            'user:read',
            'access_control:write',
        ],
    },
]

/** Merge scopes from multiple intent tiles. Write wins over read (highest-wins). */
export const mergeIntentScopes = (tileKeys: string[]): string[] => {
    const merged: Record<string, string> = {}
    for (const tileKey of tileKeys) {
        const tile = API_KEY_INTENT_TILES.find((t) => t.key === tileKey)
        if (!tile) {
            continue
        }
        for (const scope of tile.scopes) {
            const [object, action] = scope.split(':')
            if (!object || !action) {
                continue
            }
            if (!merged[object] || (action === 'write' && merged[object] === 'read')) {
                merged[object] = action
            }
        }
    }
    return Object.entries(merged).map(([object, action]) => `${object}:${action}`)
}

// --- Presets for URL-driven flows ---

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
            ['feature_flag', 'insight', 'dashboard', 'survey', 'experiment', 'event_definition'].includes(key)
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

// Scopes required by the PostHog MCP server (https://mcp.posthog.com)
// These match the scopes_supported in the MCP server's OAuth protected resource metadata
export const MCP_SERVER_OAUTH_SCOPES = [
    'openid',
    'profile',
    'email',
    'introspection',
    'user:read',
    'organization:read',
    'project:read',
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
