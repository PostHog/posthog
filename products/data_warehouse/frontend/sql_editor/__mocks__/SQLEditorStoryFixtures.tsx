import { Decorator, Meta, StoryObj } from '@storybook/react'
import { useEffect, useRef } from 'react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'
import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { AccessControlLevel, AccessControlResourceType, ChartDisplayType } from '~/types'

import { buildBIQuery } from 'products/business_intelligence/frontend/biEditorTypes'

// Grant saved-object access before the story mounts and restore it on unmount so story order can't leak.
const grantWarehouseAccess: Decorator = function GrantWarehouseAccess(Story): JSX.Element {
    const appContext = (window as any).POSTHOG_APP_CONTEXT
    const original = useRef<{ value: unknown }>()
    if (appContext && !original.current) {
        original.current = { value: appContext.resource_access_control }
        appContext.resource_access_control = {
            ...appContext.resource_access_control,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.Editor,
            [AccessControlResourceType.Endpoint]: AccessControlLevel.Editor,
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
export const SAMPLE_SQL = `SELECT
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

const HARNESS_RESULTS = {
    columns: ['harness', 'calls'],
    column_formats: ['mcp_harness', null],
    types: [
        ['harness', 'String'],
        ['calls', 'UInt64'],
    ],
    results: [
        ['Claude Code', 12],
        ['OpenAI Codex', 7],
        ['Other', 2],
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

// A worksheet restored from the URL, so the snapshot shows every shelf holding a pill
const BI_EVENTS_SOURCE = { table: 'events' }

export const biEventsField = (name: string, type: BIField['type']): BIField => ({
    id: JSON.stringify([null, 'events', name]),
    name,
    expression: name,
    type,
    source: BI_EVENTS_SOURCE,
})

export const BI_WORKSHEET_CONFIG: BIConfig = {
    source: BI_EVENTS_SOURCE,
    chartType: ChartDisplayType.ActionsLineGraph,
    rows: [{ ...biEventsField('timestamp', 'datetime'), dateBucket: 'day' }],
    columns: [biEventsField('event', 'string')],
    values: [{ field: biEventsField('revenue', 'float'), aggregation: 'sum' }],
    filters: [{ field: biEventsField('event', 'string'), operator: 'equals', value: 'purchase' }],
    limit: 1000,
    sort: null,
}

export const BI_EVENTS_FIELDS = Object.fromEntries(
    (
        [
            ['event', 'string'],
            ['distinct_id', 'string'],
            ['timestamp', 'datetime'],
            ['$is_bot', 'boolean'],
            ['properties', 'json'],
            ['user_id', 'integer'],
            ['revenue', 'float'],
            ['duration_ms', 'integer'],
        ] as const
    ).map(([name, type]) => [name, { name, hogql_value: name, type, schema_valid: true }])
)

const BI_WORKSHEET_RESULTS = {
    columns: ['bi_row_timestamp', 'bi_column_event', 'sum_revenue'],
    types: [
        ['bi_row_timestamp', 'DateTime'],
        ['bi_column_event', 'String'],
        ['sum_revenue', 'Float64'],
    ],
    results: [
        ['2026-06-01', 'purchase', 120],
        ['2026-06-02', 'purchase', 180],
        ['2026-06-03', 'purchase', 150],
    ],
    hasMore: false,
}

const pinQueryTimer = (): (() => void) => {
    const originalNow = performance.now
    performance.now = () => 0
    return () => {
        performance.now = originalNow
    }
}

export const sqlEditorStoryMeta: Meta = {
    component: App,
    title: 'Scenes-App/Data Warehouse/SQL Editor',
    decorators: [
        grantWarehouseAccess,
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard': () => [200, AVAILABLE_SOURCES],
                '/api/:scope/:team_id/external_data_sources/connections/': [],
                '/api/:scope/:team_id/external_data_sources/direct_connection_options/': [],
                '/api/projects/:team_id/query_tab_state/user': [200, { tabs: [] }],
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder/': { id: 'example-home', path: 'Users/Example' },
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    const kind = body?.query?.kind
                    if (kind === 'DatabaseSchemaQuery') {
                        return [200, { tables: {} }]
                    }
                    if (kind === 'HogQLMetadata') {
                        return [200, { errors: [], warnings: [], notices: [], isValid: true }]
                    }
                    if (body?.query?.query === 'SELECT category, revenue FROM example_sales') {
                        return [200, CHART_EXPERIMENT_RESULTS]
                    }
                    if (JSON.stringify(body?.query ?? {}).includes('$virt_mcp_harness')) {
                        return [200, HARNESS_RESULTS]
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
            waitForSelector: '.CodeEditor[data-editor-ready="true"]',
            viewport: { width: 1600, height: 900 },
        },
    },
}

export type Story = StoryObj<{}>

export const DISCARD_VIEW = {
    id: 'discard-view',
    name: 'Saved query',
    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
    columns: [],
    is_materialized: false,
    user_access_level: AccessControlLevel.Editor,
}

export const DISCARD_INSIGHT = {
    id: 42,
    short_id: 'discard1',
    name: 'Saved insight',
    description: '',
    query: { kind: 'DataVisualizationNode', source: DISCARD_VIEW.query, display: 'Auto' },
    saved: true,
    dashboards: [],
    user_access_level: AccessControlLevel.Editor,
}

export const BI_MODE_WORKSHEET_MOCKS = {
    get: {
        '/api/projects/:team_id/warehouse_expressions/': { results: [] },
        '/api/environments/:team_id/warehouse_expressions/': { results: [] },
    },
    post: {
        // The specific path wins over the catch-all query mock on the sqlEditorStoryMeta
        '/api/environments/:team_id/query/DatabaseSchemaQuery/': {
            tables: {
                events: { id: 'events', name: 'events', type: 'posthog', fields: BI_EVENTS_FIELDS },
            },
        },
        '/api/environments/:team_id/query/HogQLQuery/': BI_WORKSHEET_RESULTS,
    },
} satisfies Mocks

export const biWorksheetStory: Story = {
    beforeEach: pinQueryTimer,
    parameters: {
        // The editor restores BI state only alongside the query it generated
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({
            q: buildBIQuery(BI_WORKSHEET_CONFIG)?.query ?? '',
            mode: 'bi',
            bi: JSON.stringify(BI_WORKSHEET_CONFIG),
        })}`,
        testOptions: {
            waitForSelector: '[data-attr="bi-editor-data-pane-measure"]',
            viewport: { width: 1600, height: 900 },
        },
        msw: {
            mocks: BI_MODE_WORKSHEET_MOCKS,
        },
    },
}

export const CHART_EXPERIMENT_RESULTS = {
    columns: ['category', 'revenue'],
    types: [
        ['category', 'String'],
        ['revenue', 'Float64'],
    ],
    results: [
        ['Books', 120],
        ['Games', 240],
        ['Music', 180],
    ],
    hasMore: false,
}
