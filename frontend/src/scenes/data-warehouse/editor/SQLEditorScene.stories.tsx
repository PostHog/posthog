import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import { BindLogic } from 'kea'
import { delay } from 'msw'
import { useEffect, useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'
import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import {
    DatabaseSchemaMaterializedViewTable,
    DatabaseSchemaTableCertificationStatus,
    NodeKind,
} from '~/queries/schema/schema-general'
import type { DataWarehouseSavedQuery, InsightShortId } from '~/types'
import { AccessControlLevel, AccessControlResourceType, ChartDisplayType } from '~/types'

import { buildBIQuery } from 'products/business_intelligence/frontend/biEditorTypes'

import { expect, userEvent } from 'storybook/test'

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

// A worksheet restored from the URL, so the snapshot shows every shelf holding a pill
const BI_EVENTS_SOURCE = { table: 'events' }
const biEventsField = (name: string, type: BIField['type']): BIField => ({
    id: JSON.stringify([null, 'events', name]),
    name,
    expression: name,
    type,
    source: BI_EVENTS_SOURCE,
})
const BI_WORKSHEET_CONFIG: BIConfig = {
    source: BI_EVENTS_SOURCE,
    chartType: ChartDisplayType.ActionsLineGraph,
    rows: [{ ...biEventsField('timestamp', 'datetime'), dateBucket: 'day' }],
    columns: [biEventsField('event', 'string')],
    values: [{ field: biEventsField('revenue', 'float'), aggregation: 'sum' }],
    filters: [{ field: biEventsField('event', 'string'), operator: 'equals', value: 'purchase' }],
    limit: 1000,
    sort: null,
}
const BI_EVENTS_FIELDS = Object.fromEntries(
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
                    if (body?.query?.query === 'SELECT category, revenue FROM example_sales') {
                        return [200, CHART_EXPERIMENT_RESULTS]
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

export const LoadingInsight: Story = {
    parameters: {
        pageUrl: `${urls.sqlEditor()}?open_insight=loading1`,
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '[data-attr="hogql-query-editor"] ~ [role="status"]',
        },
        msw: {
            mocks: {
                get: {
                    '/api/:scope/:team_id/insights/': async () => {
                        await delay('infinite')
                        return [200, { results: [] }]
                    },
                    '/api/projects/:team_id/warehouse_expressions/': { results: [] },
                },
            },
        },
    },
}

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

const DISCARD_VIEW = {
    id: 'discard-view',
    name: 'Saved query',
    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
    columns: [],
    is_materialized: false,
    user_access_level: AccessControlLevel.Editor,
}
const DISCARD_INSIGHT = {
    id: 42,
    short_id: 'discard1',
    name: 'Saved insight',
    description: '',
    query: { kind: 'DataVisualizationNode', source: DISCARD_VIEW.query, display: 'Auto' },
    saved: true,
    dashboards: [],
    user_access_level: AccessControlLevel.Editor,
}

const discardMocks = {
    get: {
        '/api/projects/:team_id/warehouse_saved_queries/': [200, { results: [DISCARD_VIEW] }],
        '/api/:scope/:team_id/warehouse_saved_queries/:id/': [200, DISCARD_VIEW],
        '/api/:scope/:team_id/insights/': [200, { results: [DISCARD_INSIGHT] }],
        '/api/projects/:team_id/warehouse_expressions/': [200, { results: [] }],
        '/api/projects/:team_id/data_modeling_nodes/lineage/': [200, { nodes: [], edges: [] }],
        '/api/projects/:team_id/query_tab_state/user/': [200, { state: {} }],
    },
}

export const EditedView: Story = {
    parameters: {
        pageUrl: `${urls.sqlEditor({ view_id: DISCARD_VIEW.id })}#q=SELECT%202`,
        msw: { mocks: discardMocks },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const discard = await canvas.findByRole('button', { name: 'Discard changes' }, { timeout: 15000 })
        await waitFor(() =>
            expect(canvas.getByRole('button', { name: 'Discard changes' })).toHaveAttribute('aria-disabled', 'false')
        )
        await expect(canvas.getByText('Edited')).toBeVisible()
        await expect(canvas.getByRole('button', { name: 'Update view' })).toHaveAttribute('aria-disabled', 'true')
        await userEvent.click(discard)
        await waitFor(() =>
            expect(canvas.getByRole('button', { name: 'Discard changes' })).toHaveAttribute('aria-disabled', 'true')
        )
        await expect(canvas.queryByText('Edited')).not.toBeInTheDocument()
        await expect(canvas.getByRole('button', { name: 'Update view' })).toHaveAttribute('aria-disabled', 'true')
        sqlEditorLogic({ tabId: 'default' }).actions.setQueryInput('SELECT 2')
        await waitFor(() =>
            expect(canvas.getByRole('button', { name: 'Discard changes' })).toHaveAttribute('aria-disabled', 'false')
        )
        await userEvent.click(canvas.getByRole('button', { name: 'Run' }))
        await waitFor(
            () => expect(canvas.getByRole('button', { name: 'Update view' })).toHaveAttribute('aria-disabled', 'false'),
            {
                timeout: 15000,
            }
        )
        sqlEditorLogic({ tabId: 'default' }).actions.setQueryInput('SELECT 3')
        await waitFor(() =>
            expect(canvas.getByRole('button', { name: 'Update view' })).toHaveAttribute('aria-disabled', 'true')
        )
    },
}

export const EditedInsight: Story = {
    parameters: {
        pageUrl: `${urls.sqlEditor({ insightShortId: DISCARD_INSIGHT.short_id })}#q=SELECT%202`,
        msw: { mocks: discardMocks },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByRole('button', { name: 'Discard changes' }, { timeout: 15000 })
        await waitFor(() =>
            expect(canvas.getByRole('button', { name: 'Discard changes' })).toHaveAttribute('aria-disabled', 'false')
        )
        await waitFor(() => expect(canvas.getByText('Edited')).toBeVisible())
        await expect(canvas.getByRole('button', { name: 'Update insight' })).toHaveAttribute('aria-disabled', 'false')
        await userEvent.click(canvasElement.querySelector('[data-attr="sql-editor-save-options-button"]')!)
        const menu = within(canvasElement.ownerDocument.body)
        await expect(await menu.findByRole('menuitem', { name: 'Save as new insight...' })).toHaveAttribute(
            'aria-disabled',
            'false'
        )
        await expect(menu.getByRole('menuitem', { name: 'Save as new view...' })).toHaveAttribute(
            'aria-disabled',
            'true'
        )
        await expect(canvas.queryByRole('button', { name: /^close$/ })).not.toBeInTheDocument()
        await userEvent.click(menu.getByText('Reset view'))
        await waitFor(() => expect(canvas.queryByRole('button', { name: 'Update insight' })).not.toBeInTheDocument())
        await expect(canvas.getByRole('button', { name: 'Save as insight' })).toBeVisible()
        await expect(sqlEditorLogic({ tabId: 'default' }).values.queryInput).toEqual('SELECT 2')
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

const sidebarStatusView = (
    id: string,
    name: string,
    status: string,
    latestError: string | null,
    suspended: DataWarehouseSavedQuery['suspended'] = {}
): Partial<DataWarehouseSavedQuery> => ({
    id,
    name,
    is_materialized: true,
    status,
    latest_error: latestError,
    suspended,
    columns: [],
    managed_viewset_kind: null,
    user_access_level: AccessControlLevel.Editor,
})

const sidebarSchemaView = (
    name: string,
    certification: DatabaseSchemaTableCertificationStatus
): DatabaseSchemaMaterializedViewTable => ({
    type: 'materialized_view',
    id: name,
    name,
    fields: {},
    query: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
    certification: { status: certification },
})

export const SidebarMaterializationStatus: Story = {
    parameters: {
        testOptions: {
            waitForSelector: ['.monaco-editor', '[data-attr="menu-item-weekly_revenue"]'],
            viewport: { width: 1600, height: 900 },
        },
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': [
                        200,
                        {
                            tables: {
                                daily_signups: sidebarSchemaView('daily_signups', 'certified'),
                                orders_by_region: sidebarSchemaView('orders_by_region', 'deprecated'),
                                weekly_revenue: sidebarSchemaView('weekly_revenue', 'certified'),
                            },
                        },
                    ],
                },
                get: {
                    '/api/projects/:team_id/warehouse_expressions/': [200, { results: [] }],
                    '/api/projects/:team_id/warehouse_saved_queries/': [
                        200,
                        {
                            results: [
                                sidebarStatusView('healthy-view', 'daily_signups', 'Completed', null),
                                sidebarStatusView(
                                    'failed-view',
                                    'orders_by_region',
                                    'Failed',
                                    'QueryError: Unable to resolve field: region_code'
                                ),
                                sidebarStatusView(
                                    'paused-view',
                                    'weekly_revenue',
                                    'Failed',
                                    'This model has been suspended after 5 consecutive failed materializations. Error: QueryError: Unable to resolve field: net_amount',
                                    {
                                        clickhouse: {
                                            at: '2026-06-06T12:00:00Z',
                                            reason: 'QueryError: Unable to resolve field: net_amount',
                                            job_id: 'job-paused',
                                        },
                                    }
                                ),
                            ],
                        },
                    ],
                },
            },
        },
    },
}

export const BIModeWorksheet: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.SQL_EDITOR_BI_MODE],
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
            mocks: {
                get: {
                    '/api/projects/:team_id/warehouse_expressions/': { results: [] },
                },
                post: {
                    // The specific path wins over the catch-all query mock on the meta
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': {
                        tables: {
                            events: { id: 'events', name: 'events', type: 'posthog', fields: BI_EVENTS_FIELDS },
                        },
                    },
                },
            },
        },
    },
}

export const BIEmptyWorksheet: Story = {
    ...BIModeWorksheet,
    parameters: {
        ...BIModeWorksheet.parameters,
        // An explicit empty query prevents restoring another story's persisted worksheet.
        pageUrl: `${urls.businessIntelligence()}#q=`,
        testOptions: { waitForSelector: '[data-attr="bi-editor-data-source"]' },
    },
    play: async ({ canvasElement }) => {
        await expect(within(canvasElement).findByText('Select a table to list its fields.')).resolves.toBeVisible()
    },
}

const BI_SAVED_QUERY = {
    ...buildBIQuery(BI_WORKSHEET_CONFIG)!.node,
    kind: NodeKind.BIVisualizationNode as const,
    config: BI_WORKSHEET_CONFIG,
}
BI_SAVED_QUERY.chartSettings!.yAxis![0].settings = { formatting: { prefix: '$', suffix: '' } }
BI_SAVED_QUERY.tableSettings = {
    columns: ['bi_row_timestamp', 'bi_column_event', 'sum_revenue'].map((column) => ({
        column,
        settings: { formatting: { prefix: '', suffix: '' } },
    })),
}

const BI_SAVED_INSIGHT = {
    ...DISCARD_INSIGHT,
    short_id: 'bisaved1',
    name: 'Revenue by event',
    query: BI_SAVED_QUERY,
}

export const BISavedInsight: Story = {
    ...BIModeWorksheet,
    parameters: {
        ...BIModeWorksheet.parameters,
        pageUrl: urls.insightView('bisaved1' as InsightShortId),
        testOptions: { waitForSelector: '[data-attr="insight-edit-button"]', viewport: { width: 1600, height: 900 } },
        msw: {
            mocks: {
                ...BIModeWorksheet.parameters?.msw.mocks,
                get: {
                    ...BIModeWorksheet.parameters?.msw.mocks.get,
                    '/api/:scope/:team_id/insights/': [200, { results: [BI_SAVED_INSIGHT] }],
                    '/api/environments/:team_id/insights/:id/': [200, BI_SAVED_INSIGHT],
                    '/api/projects/:team_id/events_retention/': [200, { retention_months: null, retained_from: null }],
                },
                post: {
                    ...BIModeWorksheet.parameters?.msw.mocks.post,
                    '/api/environments/:team_id/query/HogQLQuery/': {
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
                    },
                },
            },
        },
    },
}

export const BIEditSavedInsight: Story = {
    ...BISavedInsight,
    parameters: {
        ...BISavedInsight.parameters,
        pageUrl: urls.businessIntelligence({ insightShortId: 'bisaved1' }),
        testOptions: BIModeWorksheet.parameters?.testOptions,
    },
    play: async ({ canvasElement }) => {
        await waitFor(() =>
            expect(canvasElement.querySelector('[data-attr="bi-editor-data-pane-measure"]')).not.toBeNull()
        )
        await waitFor(() =>
            expect(within(canvasElement).queryByText('Edited', { exact: true })).not.toBeInTheDocument()
        )
    },
}

export const BICalculatedMeasureEditor: Story = {
    ...BIModeWorksheet,
    parameters: {
        ...BIModeWorksheet.parameters,
        testOptions: {
            waitForSelector: '[data-attr="bi-calculated-measure-modal"] .monaco-editor',
            viewport: { width: 1050, height: 900 },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const addMeasure = await canvas.findByText('Add calculated measure', {}, { timeout: 15000 })
        await waitFor(() => expect(addMeasure.closest('button')).toBeEnabled())
        await userEvent.click(addMeasure)
        const modal = within(canvasElement.ownerDocument.body)
        await userEvent.type(await modal.findByLabelText('Name'), 'ARPU')
    },
}

const BI_QUICK_FILTERS_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsTable,
    columns: [],
    values: [
        {
            field: biEventsField('revenue', 'float'),
            aggregation: 'custom',
            label: 'ARPU',
            customExpression: 'sum(revenue) / nullIf(count(DISTINCT user_id), 0)',
        },
    ],
    filters: [
        { field: biEventsField('event', 'string'), operator: 'in', value: '', values: ['purchase', 'renewal'] },
        {
            field: biEventsField('timestamp', 'datetime'),
            operator: 'between',
            value: '2026-06-01 00:00:00',
            valueTo: '2026-06-07 23:59:59',
        },
    ],
}

export const BIQuickFilters: Story = {
    ...BIModeWorksheet,
    parameters: {
        ...BIModeWorksheet.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({ q: buildBIQuery(BI_QUICK_FILTERS_CONFIG)?.query ?? '', mode: 'bi', bi: JSON.stringify(BI_QUICK_FILTERS_CONFIG) })}`,
        msw: {
            mocks: {
                ...BIModeWorksheet.parameters?.msw.mocks,
                post: {
                    ...BIModeWorksheet.parameters?.msw.mocks.post,
                    '/api/environments/:team_id/query/HogQLQuery/': async ({ request }: { request: Request }) => {
                        const { query } = await request.json()
                        return [
                            200,
                            query.query.startsWith('SELECT DISTINCT')
                                ? {
                                      columns: ['value'],
                                      types: ['String'],
                                      results: [['purchase'], ['renewal'], ['refund'], ['trial_started']],
                                      hasMore: false,
                                  }
                                : {
                                      columns: ['toStartOfDay(timestamp)', 'ARPU'],
                                      types: ['DateTime', 'Float64'],
                                      hasMore: false,
                                      results: [24, 28, 26, 31, 35, 33, 38].map((value, index) => [
                                          `2026-06-0${index + 1} 00:00:00`,
                                          value,
                                      ]),
                                  },
                        ]
                    },
                },
            },
        },
    },
}

export const BIQuickFiltersNarrow: Story = {
    ...BIQuickFilters,
    parameters: {
        ...BIQuickFilters.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({
            mode: 'bi',
            bi: JSON.stringify({
                ...BI_QUICK_FILTERS_CONFIG,
                filters: [
                    ...BI_QUICK_FILTERS_CONFIG.filters,
                    {
                        field: biEventsField('properties.region', 'string'),
                        operator: 'in',
                        value: '',
                        values: ['North', 'West'],
                    },
                    {
                        field: biEventsField('properties.device', 'string'),
                        operator: 'in',
                        value: '',
                        values: ['Desktop'],
                    },
                    {
                        field: biEventsField('properties.channel', 'string'),
                        operator: 'not_in',
                        value: '',
                        values: ['Internal'],
                    },
                    { field: biEventsField('revenue', 'float'), operator: 'between', value: '0', valueTo: '1000' },
                    { field: biEventsField('duration_ms', 'integer'), operator: 'less_than', value: '5000' },
                    { field: biEventsField('distinct_id', 'string'), operator: 'is_set', value: '' },
                ],
            } satisfies BIConfig),
        })}`,
        testOptions: {
            waitForSelector: '[data-attr="bi-editor-filters-pill"]',
            viewport: { width: 1050, height: 900 },
        },
    },
}

export const LazySchema: Story = {
    parameters: {
        pageUrl: urls.sqlEditor({ query: 'SELECT * FROM events LIMIT 100' }),
        testOptions: {
            waitForSelector: ['.monaco-editor', '[data-attr="menu-item-posthog"]'],
        },
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

export const BIDataSourcePicker: Story = {
    ...BIModeWorksheet,
    parameters: {
        ...BIModeWorksheet.parameters,
        testOptions: {
            waitForSelector: '[data-attr="bi-editor-data-source-picker"]',
            viewport: { width: 1280, height: 800 },
        },
        msw: {
            mocks: {
                ...BIModeWorksheet.parameters?.msw.mocks,
                post: {
                    ...BIModeWorksheet.parameters?.msw.mocks.post,
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': {
                        tables: {
                            events: { id: 'events', name: 'events', type: 'posthog', fields: BI_EVENTS_FIELDS },
                            persons: { id: 'persons', name: 'persons', type: 'posthog', fields: {} },
                            stripe_customers: {
                                id: 'stripe_customers',
                                name: 'stripe_customers',
                                type: 'data_warehouse',
                                fields: {},
                                source: { id: 'example-stripe', source_type: 'Stripe', prefix: 'stripe_' },
                            },
                            stripe_invoices: {
                                id: 'stripe_invoices',
                                name: 'stripe_invoices',
                                type: 'data_warehouse',
                                fields: {},
                                source: { id: 'example-stripe', source_type: 'Stripe', prefix: 'stripe_' },
                            },
                            postgres_orders: {
                                id: 'postgres_orders',
                                name: 'postgres_orders',
                                type: 'data_warehouse',
                                fields: {},
                                source: { id: 'example-postgres', source_type: 'Postgres', prefix: 'postgres_' },
                            },
                        },
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')).toBeVisible(), {
            timeout: 15000,
        })
        await waitFor(() => expect(canvas.queryByText('Locate')).not.toBeInTheDocument())
        await userEvent.click(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')!)
        const page = within(canvasElement.ownerDocument.body)
        await waitFor(() => expect(page.getByRole('searchbox', { name: 'Search tables' })).toBeVisible())
    },
}

const CHART_EXPERIMENT_RESULTS = {
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

const chartExperimentParameters = (approved: boolean, decisionDelay = 0, queryDelay = 0): Record<string, unknown> => ({
    featureFlags: ['ml-inference-decisions', 'jev-chart-autodetection'],
    pageUrl: urls.sqlEditor({ query: 'SELECT category, revenue FROM example_sales' }),
    msw: {
        mocks: {
            get: {
                '/api/organizations/@current/': {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: approved,
                },
                '/api/projects/:team_id/warehouse_expressions/': { results: [] },
            },
            post: {
                '/api/environments/:team_id/query/HogQLMetadata': async ({ request }: MockResolverInfo) => {
                    const body = (await request.json()) as { query: { includeOutputTypes?: boolean } }
                    return [
                        200,
                        {
                            isValid: true,
                            errors: [],
                            warnings: [],
                            notices: [],
                            output_columns: body.query.includeOutputTypes
                                ? [
                                      { name: 'category', type: 'String' },
                                      { name: 'revenue', type: 'Float64' },
                                  ]
                                : undefined,
                        },
                    ]
                },
                '/api/environments/:team_id/query/HogQLQuery': async () => {
                    await delay(queryDelay)
                    return [200, CHART_EXPERIMENT_RESULTS]
                },
                '/api/projects/:team_id/ml_inference/decisions/decide/': async () => {
                    await delay(decisionDelay)
                    return [
                        200,
                        {
                            model: 'test',
                            input_tokens: 1,
                            latency_ms: 1,
                            answers: Object.fromEntries(
                                Object.entries({
                                    chart: 'ActionsBar',
                                    layout: 'both',
                                    x: 'c0',
                                    value: 'c1',
                                    dimension: 'none',
                                }).map(([id, choice]) => [
                                    id,
                                    {
                                        type: 'choice',
                                        choice,
                                        confidence: 1,
                                        probability: null,
                                        probabilities: {},
                                        score: null,
                                    },
                                ])
                            ),
                        },
                    ]
                },
            },
        },
    },
})

const withAIConsent = (approved: boolean): Decorator =>
    function AIConsentStory(Story): JSX.Element {
        useEffect(() => {
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: approved,
            })
        }, [])
        return <Story />
    }

export const JevChartAndTable: Story = {
    // These interactive scenarios need Run; automatic snapshots only capture the same idle editor.
    tags: ['test-skip'],
    parameters: chartExperimentParameters(true),
    decorators: [withAIConsent(true)],
}

export const JevWithoutConsent: Story = {
    tags: ['test-skip'],
    parameters: chartExperimentParameters(false),
    decorators: [withAIConsent(false)],
}

export const JevChoosingChart: Story = {
    tags: ['test-skip'],
    parameters: chartExperimentParameters(true, 3000),
    decorators: [withAIConsent(true)],
}

export const JevChartTimeout: Story = {
    tags: ['test-skip'],
    parameters: chartExperimentParameters(true, 6000),
    decorators: [withAIConsent(true)],
}

export const JevEarlySelection: Story = {
    tags: ['test-skip'],
    parameters: chartExperimentParameters(true, 100, 3000),
    decorators: [withAIConsent(true)],
}
const BI_CONNECTIONS_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsTable,
    rows: [],
    columns: [],
    filters: [],
}

export const BIConnections: Story = {
    ...BIModeWorksheet,
    parameters: {
        ...BIModeWorksheet.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({
            q: buildBIQuery(BI_CONNECTIONS_CONFIG)?.query ?? '',
            mode: 'bi',
            bi: JSON.stringify(BI_CONNECTIONS_CONFIG),
        })}`,
        testOptions: {
            waitForSelector: '[data-attr="bi-editor-connection-fields"] [data-attr="bi-editor-connection-fields"]',
            viewport: { width: 1280, height: 900 },
        },
        msw: {
            mocks: {
                ...BIModeWorksheet.parameters?.msw.mocks,
                post: {
                    ...BIModeWorksheet.parameters?.msw.mocks.post,
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': {
                        tables: {
                            events: {
                                id: 'events',
                                name: 'events',
                                type: 'posthog',
                                fields: {
                                    event: BI_EVENTS_FIELDS.event,
                                    revenue: BI_EVENTS_FIELDS.revenue,
                                    person: {
                                        name: 'person',
                                        type: 'lazy_table',
                                        table: 'persons',
                                        schema_valid: true,
                                        hogql_value: 'person',
                                    },
                                },
                            },
                            persons: {
                                id: 'persons',
                                name: 'persons',
                                type: 'posthog',
                                fields: {
                                    email: { name: 'email', type: 'string', schema_valid: true, hogql_value: 'email' },
                                    lifetime_value: {
                                        name: 'lifetime_value',
                                        type: 'float',
                                        schema_valid: true,
                                        hogql_value: 'lifetime_value',
                                    },
                                    company: {
                                        name: 'company',
                                        type: 'lazy_table',
                                        table: 'companies',
                                        schema_valid: true,
                                        hogql_value: 'company',
                                    },
                                },
                            },
                            companies: {
                                id: 'companies',
                                name: 'companies',
                                type: 'data_warehouse',
                                fields: {
                                    name: { name: 'name', type: 'string', schema_valid: true, hogql_value: 'name' },
                                    annual_revenue: {
                                        name: 'annual_revenue',
                                        type: 'decimal',
                                        schema_valid: true,
                                        hogql_value: 'annual_revenue',
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')).toBeVisible(), {
            timeout: 15000,
        })
        const autoUpdate = canvasElement.querySelector('[data-attr="bi-editor-auto-update"]')!
        if (autoUpdate.getAttribute('aria-checked') === 'true') {
            await userEvent.click(autoUpdate)
        }
        await userEvent.click(await canvas.findByRole('button', { name: 'person' }))
        await userEvent.click(await canvas.findByRole('button', { name: 'person.company' }))
        await waitFor(() => expect(canvas.getByText('annual_revenue')).toBeVisible())
    },
}

const BI_ANALYSIS_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsTable,
    values: [
        { field: biEventsField('revenue', 'float'), aggregation: 'sum', tableCalculation: { type: 'running_total' } },
        { field: biEventsField('revenue', 'float'), aggregation: 'average' },
    ],
    topN: { fieldId: biEventsField('event', 'string').id, count: 5, measureIndex: 0, includeOther: true },
    totals: { rows: true, subtotals: true },
}

export const BITableAnalysis: Story = {
    ...BIModeWorksheet,
    parameters: {
        ...BIModeWorksheet.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({
            q: buildBIQuery(BI_ANALYSIS_CONFIG)!.query,
            mode: 'bi',
            bi: JSON.stringify(BI_ANALYSIS_CONFIG),
        })}`,
        msw: {
            mocks: {
                ...BIModeWorksheet.parameters?.msw.mocks,
                post: {
                    ...BIModeWorksheet.parameters?.msw.mocks.post,
                    '/api/environments/:team_id/query/HogQLQuery/': {
                        columns: ['bi_row_timestamp', 'bi_column_event', 'sum_revenue', 'average_revenue_2'],
                        types: [
                            ['bi_row_timestamp', 'String'],
                            ['bi_column_event', 'String'],
                            ['sum_revenue', 'Nullable(Float64)'],
                            ['average_revenue_2', 'Float64'],
                        ],
                        results: [
                            ['Total', 'Total', null, 14.2],
                            ['2026-06-01', 'purchase', 120, 12],
                            ['2026-06-02', 'purchase', 300, 15],
                            ['2026-06-01', 'Other', 40, 10],
                        ],
                        hasMore: false,
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')).toBeVisible())
        await userEvent.click(await canvas.findByRole('button', { name: /^Run$/ }))
        await waitFor(() => expect(canvas.getAllByText('Total').length).toBeGreaterThan(0))
    },
}

const BI_COMBO_CONFIG: BIConfig = {
    ...BI_WORKSHEET_CONFIG,
    chartType: ChartDisplayType.ActionsBar,
    columns: [],
    values: [
        {
            field: biEventsField('revenue', 'float'),
            aggregation: 'sum',
            formatting: { style: 'number', prefix: '$', decimalPlaces: 2 },
            display: { label: 'Revenue', displayType: 'bar', yAxisPosition: 'left' },
        },
        {
            field: biEventsField('revenue', 'float'),
            aggregation: 'average',
            formatting: { style: 'number', prefix: '$', decimalPlaces: 2 },
            display: { label: 'Average order', displayType: 'line', yAxisPosition: 'right' },
        },
    ],
}

export const BICombinedMeasures: Story = {
    ...BIModeWorksheet,
    parameters: {
        ...BIModeWorksheet.parameters,
        pageUrl: `${urls.businessIntelligence()}#${new URLSearchParams({ q: buildBIQuery(BI_COMBO_CONFIG)!.query, mode: 'bi', bi: JSON.stringify(BI_COMBO_CONFIG) })}`,
        msw: {
            mocks: {
                ...BIModeWorksheet.parameters?.msw.mocks,
                post: {
                    ...BIModeWorksheet.parameters?.msw.mocks.post,
                    '/api/environments/:team_id/query/HogQLQuery/': {
                        columns: ['toStartOfDay(timestamp)', 'sum_revenue', 'average_revenue_2'],
                        types: [
                            ['toStartOfDay(timestamp)', 'DateTime'],
                            ['sum_revenue', 'Float64'],
                            ['average_revenue_2', 'Float64'],
                        ],
                        results: [
                            ['2026-06-01', 1200, 12.5],
                            ['2026-06-02', 2100, 15.2],
                            ['2026-06-03', 1800, 13.4],
                            ['2026-06-04', 2450, 16.8],
                        ],
                        hasMore: false,
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="bi-editor-data-source"]')).toBeVisible())
        await userEvent.click(await canvas.findByRole('button', { name: /^Run$/ }))
        await waitFor(() => expect(canvasElement.querySelector('canvas')).not.toBeNull())
    },
}

export const BIMeasureDisplay: Story = {
    ...BICombinedMeasures,
    play: async ({ canvasElement }) => {
        await userEvent.click((await within(canvasElement).findAllByRole('button', { name: 'Format and display' }))[0])
    },
}
