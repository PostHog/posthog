import { Decorator, Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useEffect, useRef } from 'react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { DataWarehouseSavedQuery } from '~/types'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { QueryInfo } from './output-pane-tabs/QueryInfo'
import { sqlEditorLogic } from './sqlEditorLogic'

// The SQL editor scene gates on warehouse-objects access; grant it on the storybook app context
// before the story mounts and restore the original on unmount so story order can't leak.
const grantWarehouseAccess: Decorator = function GrantWarehouseAccess(Story): JSX.Element {
    const appContext = (window as any).POSTHOG_APP_CONTEXT
    const original = useRef<{ value: unknown }>()
    if (appContext && !original.current) {
        original.current = { value: appContext.resource_access_control }
        appContext.resource_access_control = {
            ...appContext.resource_access_control,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.Editor,
        }
    }
    useEffect(
        () => () => {
            if (appContext && original.current) {
                appContext.resource_access_control = original.current.value
            }
        },
        [appContext]
    )
    return <Story />
}

// Top tools per server — mirrors the first recipe in the MCP analytics docs (queries.mdx).
const SAMPLE_SQL = `SELECT
    properties.$mcp_server_name AS server,
    properties.$mcp_tool_name AS tool,
    count() AS calls,
    round(avg(toFloat(properties.$mcp_duration_ms))) AS avg_duration_ms,
    countIf(toBool(properties.$mcp_is_error)) AS errors
FROM events
WHERE event = 'mcp_tool_call' AND timestamp > now() - INTERVAL 7 DAY
GROUP BY server, tool
ORDER BY calls DESC
LIMIT 20`

// Mock results for the "top tools per server" query. The visual-regression snapshot captures the
// editor with the query pre-loaded but NOT run (driving Run in the snapshot races the async query
// against Storybook's story-prepare step and flakes). These results back the query when a human
// presses Run locally — that's how the doc screenshot with a populated grid was captured.
const SQL_RESULTS = {
    columns: ['server', 'tool', 'calls', 'avg_duration_ms', 'errors'],
    types: ['String', 'String', 'UInt64', 'Float64', 'UInt64'],
    hasMore: false,
    results: [
        ['posthog', 'execute-sql', 1480, 3525, 144],
        ['posthog', 'read-data-schema', 760, 1298, 3],
        ['posthog', 'query-trends', 540, 2122, 5],
        ['posthog', 'insight-create', 410, 727, 8],
        ['posthog', 'dashboard-create', 260, 940, 2],
        ['posthog', 'feature-flag-list', 180, 510, 1],
        ['posthog', 'cohort-create', 95, 1620, 6],
        ['filesystem', 'exec', 5200, 2290, 208],
        ['filesystem', 'read-file', 980, 180, 3],
        ['filesystem', 'write-file', 420, 240, 11],
    ],
}

// The empty-warehouse notice in the sidebar renders a SourceIcon per provider, each of which shows a
// LemonSkeleton until availableSourcesLogic resolves. Without this mock the skeletons never settle and
// the visual-regression runner times out waiting for loaders to disappear.
const AVAILABLE_SOURCES = {
    Postgres: { name: 'Postgres', iconPath: '/static/services/postgres.png', fields: [], caption: '', featured: true },
    Stripe: { name: 'Stripe', iconPath: '/static/services/stripe.png', fields: [], caption: '', featured: true },
    GoogleAds: {
        name: 'GoogleAds',
        iconPath: '/static/services/google-ads.png',
        fields: [],
        caption: '',
        featured: true,
    },
}

// A managed warehouse's name is long enough to outgrow the database-tree sidebar, which is what made
// the connection selector's label wrap and spill over the toolbar (support ticket 65030).
// ManagedWarehouseConnection below is the visual-regression guard for that truncation.
const MANAGED_WAREHOUSE_CONNECTION_ID = '01931b3a-0000-0000-0000-000000000001'
const MANAGED_WAREHOUSE_CONNECTIONS = [
    {
        id: MANAGED_WAREHOUSE_CONNECTION_ID,
        prefix: 'managed_warehouse',
        engine: 'duckdb',
        source_type: 'Postgres',
        access_method: 'direct',
        supports_hogql: true,
        is_builtin_managed_warehouse: true,
        description: null,
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Warehouse/SQL Editor',
    decorators: [
        grantWarehouseAccess,
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard': () => [200, AVAILABLE_SOURCES],
            },
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    const kind = body?.query?.kind
                    if (kind === 'DatabaseSchemaQuery') {
                        return [200, { tables: {} }]
                    }
                    if (kind === 'HogQLMetadata') {
                        return [200, { errors: [], warnings: [], notices: [], isValid: true }]
                    }
                    return [200, SQL_RESULTS]
                },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-07',
        // open_query pre-fills the editor with SAMPLE_SQL but does not auto-run it, so the snapshot
        // captures the loaded query with an empty results pane. (SQL_RESULTS backs the query when Run
        // is pressed locally — see its comment.)
        pageUrl: urls.sqlEditor({ query: SAMPLE_SQL }),
        testOptions: {
            waitForSelector: '.monaco-editor',
            viewport: { width: 1600, height: 900 },
        },
    },
}
export default meta

type Story = StoryObj<{}>
export const TopToolsPerServer: Story = {}

// Selecting the managed warehouse puts its long name in the sidebar's connection selector, where it
// has to ellipsize on one line rather than wrap or overflow into the Run button's toolbar.
export const ManagedWarehouseConnection: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/external_data_sources/connections': () => [
                        200,
                        MANAGED_WAREHOUSE_CONNECTIONS,
                    ],
                    '/api/projects/:team_id/external_data_sources/direct_connection_options': () => [200, []],
                },
            },
        },
        // The `c` hash param preselects the connection, so the selector renders the long label
        // instead of the default "PostHog (ClickHouse)".
        pageUrl: urls.sqlEditor({ query: SAMPLE_SQL, connectionId: MANAGED_WAREHOUSE_CONNECTION_ID }),
    },
}

const SETTINGS_VIEW = {
    id: 'settings-view',
    name: 'revenue_summary',
    is_materialized: true,
    user_access_level: AccessControlLevel.Editor,
    sync_frequency: '1hour',
    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
} as DataWarehouseSavedQuery

export const MaterializationSettings: StoryObj = {
    // This story renders the info pane on its own, so the editor the meta waits for never mounts.
    parameters: {
        testOptions: {
            waitForSelector: '[data-attr="sql-editor-sidebar-query-info-pane"]',
            viewport: { width: 1600, height: 900 },
        },
    },
    render: () => (
        <BindLogic logic={sqlEditorLogic} props={{ tabId: 'settings-preview' }}>
            <QueryInfo tabId="settings-preview" view={SETTINGS_VIEW} tabbed />
        </BindLogic>
    ),
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/': [200, SETTINGS_VIEW],
                '/api/projects/:team_id/data_modeling_jobs/': [200, { results: [], count: 0, next: null }],
                '/api/environments/:team_id/data_modeling_nodes/lineage/': [
                    200,
                    {
                        nodes: [
                            {
                                id: 'source',
                                name: 'orders',
                                type: 'table',
                                dag: 'dag-1',
                                upstream_count: 0,
                                downstream_count: 1,
                            },
                            {
                                id: 'summary',
                                name: 'revenue_summary',
                                type: 'matview',
                                saved_query_id: 'settings-view',
                                dag: 'dag-1',
                                upstream_count: 1,
                                downstream_count: 0,
                            },
                        ],
                        edges: [
                            { id: 'edge-1', source_id: 'source', target_id: 'summary', dag: 'dag-1', properties: {} },
                        ],
                    },
                ],
            },
        }),
    ],
}

export const LazySchema: Story = {
    parameters: {
        pageUrl: urls.sqlEditor({ query: 'SELECT * FROM events LIMIT 100' }),
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/warehouse_expressions/': { results: [] },
                    '/api/projects/:team_id/warehouse_saved_queries/': {
                        results: [
                            {
                                id: 'saved-view',
                                name: 'saved_events',
                                status: 'Completed',
                                columns: [],
                                managed_viewset_kind: null,
                            },
                        ],
                    },
                    '/api/projects/:team_id/query_tab_state/user/': { tabs: [] },
                },
                post: {
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': async ({
                        request,
                    }: {
                        request: Request
                    }) => {
                        const { query } = (await request.json()) as {
                            query: { kind: string; includeFields?: boolean; tables?: string[] }
                        }
                        const tables = {
                            ...Object.fromEntries(
                                [
                                    'groups',
                                    'sessions',
                                    'logs',
                                    'cohort_people',
                                    'session_replay_events',
                                    'posthog.flag_evaluations',
                                    'posthog.trace_spans',
                                    'posthog.metrics',
                                    'posthog.metric_series',
                                ].map((name) => [
                                    name,
                                    {
                                        id: name,
                                        name,
                                        type: 'posthog',
                                        fields: {
                                            id: { name: 'id', hogql_value: 'id', type: 'string', schema_valid: true },
                                        },
                                    },
                                ])
                            ),
                            events: {
                                id: 'events',
                                name: 'events',
                                type: 'posthog',
                                fields: {
                                    uuid: { name: 'uuid', hogql_value: 'uuid', type: 'string', schema_valid: true },
                                    saved: {
                                        name: 'saved',
                                        hogql_value: 'saved',
                                        type: 'view',
                                        schema_valid: true,
                                        table: 'saved_events',
                                        fields: ['event', 'person'],
                                    },
                                    person: {
                                        name: 'person',
                                        hogql_value: 'person',
                                        type: 'lazy_table',
                                        schema_valid: true,
                                        table: 'persons',
                                    },
                                },
                            },
                            'posthog.ai_events': {
                                id: 'posthog.ai_events',
                                name: 'posthog.ai_events',
                                type: 'posthog',
                                fields: {
                                    uuid: { name: 'uuid', hogql_value: 'uuid', type: 'string', schema_valid: true },
                                    event: { name: 'event', hogql_value: 'event', type: 'string', schema_valid: true },
                                    timestamp: {
                                        name: 'timestamp',
                                        hogql_value: 'timestamp',
                                        type: 'datetime',
                                        schema_valid: true,
                                    },
                                    properties: {
                                        name: 'properties',
                                        hogql_value: 'properties',
                                        type: 'json',
                                        schema_valid: true,
                                    },
                                },
                            },
                            saved_events: {
                                id: 'saved-view',
                                name: 'saved_events',
                                type: 'view',
                                fields: {
                                    event: { name: 'event', hogql_value: 'event', type: 'string', schema_valid: true },
                                    person: {
                                        name: 'person',
                                        hogql_value: 'person',
                                        type: 'lazy_table',
                                        schema_valid: true,
                                        table: 'persons',
                                    },
                                },
                            },
                            persons: {
                                id: 'persons',
                                name: 'persons',
                                type: 'posthog',
                                fields: {
                                    id: { name: 'id', hogql_value: 'id', type: 'string', schema_valid: true },
                                },
                            },
                        }
                        return [
                            200,
                            {
                                tables: Object.fromEntries(
                                    Object.entries(tables)
                                        .sort(([a], [b]) => a.localeCompare(b))
                                        .filter(([name]) => !query.tables || query.tables.includes(name))
                                        .map(([name, table]) => [
                                            name,
                                            { ...table, fields: query.includeFields === false ? {} : table.fields },
                                        ])
                                ),
                            },
                        ]
                    },
                },
            },
        },
    },
}
