import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import { BindLogic } from 'kea'
import { delay } from 'msw'
import { useEffect } from 'react'

import { mcpHintLogic } from 'lib/components/MCPHint/mcpHintLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { QueryInfo } from 'scenes/data-warehouse/editor/output-pane-tabs/QueryInfo'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { IMAGE_QUERY, IMAGE_RESULTS } from '~/queries/nodes/HogQLX/image.fixtures'
import {
    DatabaseSchemaMaterializedViewTable,
    DatabaseSchemaTableCertificationStatus,
    NodeKind,
} from '~/queries/schema/schema-general'
import type { DataWarehouseSavedQuery } from '~/types'
import { AccessControlLevel } from '~/types'

import { expect, userEvent } from 'storybook/test'

import { SAMPLE_SQL, Story, CHART_EXPERIMENT_RESULTS, sqlEditorStoryMeta } from './__mocks__/SQLEditorStoryFixtures'

const meta: Meta = { ...sqlEditorStoryMeta, component: App, title: 'Scenes-App/Data Warehouse/SQL Editor' }
export default meta

const HARNESS_SQL = `SELECT properties.$virt_mcp_harness AS harness, count() AS calls
FROM events
WHERE event = '$mcp_tool_call'
GROUP BY harness
ORDER BY calls DESC`

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

export const TopToolsPerServer: Story = {}

export const CustomerImages: Story = {
    tags: ['hogqlx-images'],
    beforeEach: () => {
        // Keep capture within the viewport so Playwright does not resize Monaco and change query wrapping.
        document.body.classList.add('storybook-viewport-layout')
        return () => document.body.classList.remove('storybook-viewport-layout')
    },
    parameters: {
        pageUrl: urls.sqlEditor({ query: IMAGE_QUERY }),
        testOptions: { waitForSelector: 'img[alt="Custom SVG"]', viewport: { width: 1600, height: 900 } },
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/HogQLQuery/': IMAGE_RESULTS,
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const editor = sqlEditorLogic({ tabId: 'default' })
        await waitFor(() => {
            expect(editor.values.queryInput).toBe(IMAGE_QUERY)
            expect(dataNodeLogic.findMounted({ key: editor.values.dataLogicKey })).toBeDefined()
        })
        const runButton = canvasElement.querySelector('[data-attr="sql-editor-run-button"]')
        expect(runButton).not.toBeNull()
        await userEvent.click(runButton!)
        await waitFor(() => {
            const image = canvasElement.querySelector('img[alt="Custom SVG"]')
            expect(image).not.toBeNull()
            expect(image!.getBoundingClientRect().height).toBeLessThanOrEqual(24)
            const labels = canvasElement.querySelectorAll('[data-attr="hogqlx-brand-mark-label"]')
            expect(Array.from(labels, (label) => label.textContent)).toEqual(['true', 'false'])
        })
        const dataLogic = dataNodeLogic.findMounted({ key: editor.values.dataLogicKey })!
        dataLogic.actions.setElapsedTime(180)
    },
}

export const HostedTrino: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.MANAGED_TRINO_QUERY],
        pageUrl: `${urls.sqlEditor({ query: 'SELECT event FROM events' })}#engine=managed_trino`,
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/warehouse_expressions/': { results: [] },
                    '/api/environments/:team_id/warehouse_expressions/': { results: [] },
                },
            },
        },
    },
}

export const HarnessLogoInResults: Story = {
    tags: ['harness-result-visual'],
    parameters: {
        pageUrl: urls.sqlEditor({ query: HARNESS_SQL }),
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/mcp_analytics/custom_harnesses/': [],
                },
            },
        },
        testOptions: {
            waitForSelector: '.rdg [data-attr="hogqlx-brand-mark-label"]',
            viewport: { width: 1600, height: 900 },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(
            () => {
                const logic = sqlEditorLogic({ tabId: 'default' })
                expect(logic.values.queryInput).toBe(HARNESS_SQL)
                expect(dataNodeLogic.findMounted({ key: logic.values.dataLogicKey })).toBeTruthy()
            },
            { timeout: 15000 }
        )
        const runButton = await canvas.findByRole('button', { name: 'Run' }, { timeout: 15000 })
        await waitFor(() => expect(runButton).toHaveAttribute('aria-disabled', 'false'), { timeout: 15000 })
        mcpHintLogic.actions.recordShown(Date.now())
        await userEvent.click(runButton)
        await expect(
            await canvas.findByText('Claude Code', { selector: '.rdg span' }, { timeout: 15000 })
        ).toBeVisible()
        await expect(canvas.getByText('OpenAI Codex')).toBeVisible()
        const logic = sqlEditorLogic({ tabId: 'default' })
        dataNodeLogic.findMounted({ key: logic.values.dataLogicKey })!.actions.setElapsedTime(180)
    },
}

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
                    '/api/environments/:team_id/warehouse_expressions/': { results: [] },
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

const SETTINGS_VIEW = {
    id: 'settings-view',
    name: 'revenue_summary',
    is_materialized: true,
    user_access_level: AccessControlLevel.Editor,
    sync_frequency: '1hour',
    query: { kind: 'HogQLQuery', query: 'SELECT 1' },
} as DataWarehouseSavedQuery

export const MaterializationSettings: StoryObj = {
    // This story renders the info pane on its own, so the editor the sqlEditorStoryMeta waits for never mounts.
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
                                upstream_count: 0,
                                downstream_count: 1,
                            },
                            {
                                id: 'summary',
                                name: 'revenue_summary',
                                type: 'matview',
                                saved_query_id: 'settings-view',
                                upstream_count: 1,
                                downstream_count: 0,
                            },
                        ],
                        edges: [{ id: 'edge-1', source_id: 'source', target_id: 'summary', properties: {} }],
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
                    '/api/environments/:team_id/warehouse_expressions/': { results: [] },
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

const chartExperimentParameters = (approved: boolean, decisionDelay = 0, queryDelay = 0): Record<string, unknown> => ({
    featureFlags: ['ml-inference-decisions'],
    pageUrl: urls.sqlEditor({ query: 'SELECT category, revenue FROM example_sales' }),
    msw: {
        mocks: {
            get: {
                '/api/organizations/@current/': {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: approved,
                },
                '/api/projects/:team_id/warehouse_expressions/': { results: [] },
                '/api/environments/:team_id/warehouse_expressions/': { results: [] },
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

const sidebarKindSchemaView = (name: string, isMaterialized: boolean): Record<string, unknown> => ({
    type: isMaterialized ? 'materialized_view' : 'view',
    id: name,
    name,
    fields: {},
    query: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
})

const sidebarKindView = (
    name: string,
    isMaterialized: boolean,
    syncFrequency?: string,
    description?: string
): Partial<DataWarehouseSavedQuery> => ({
    id: name,
    name,
    description,
    is_materialized: isMaterialized,
    sync_frequency: syncFrequency,
    status: 'Completed',
    latest_error: null,
    columns: [],
    managed_viewset_kind: null,
    user_access_level: AccessControlLevel.Editor,
})

const SIDEBAR_KIND_VIEWS = [
    sidebarKindView('orders_by_day', false),
    sidebarKindView('shop_fulfilment_queue_cost', false, undefined, 'Cost of each fulfilment queue'),
    sidebarKindView('shop_returns_unit_economics_monthly', false),
    sidebarKindView('shop_fulfilment_queue_share_monthly', true, '6hour'),
    sidebarKindView('shop_dash_region_monthly_orders', true, '24hour', 'Orders per region, one row per month'),
    sidebarKindView('shop_dash_storefront_weekly_active_sessions', true, '1hour'),
    sidebarKindView('carts', true, '24hour'),
]

export const SidebarViewKinds: Story = {
    parameters: {
        testOptions: {
            waitForSelector: ['.monaco-editor', '[data-attr="menu-item-carts"]'],
            viewport: { width: 1600, height: 900 },
        },
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/DatabaseSchemaQuery/': [
                        200,
                        {
                            tables: Object.fromEntries(
                                SIDEBAR_KIND_VIEWS.map((view) => [
                                    view.name,
                                    sidebarKindSchemaView(view.name!, !!view.is_materialized),
                                ])
                            ),
                        },
                    ],
                },
                get: {
                    '/api/projects/:team_id/warehouse_expressions/': [200, { results: [] }],
                    '/api/projects/:team_id/warehouse_saved_queries/': [200, { results: SIDEBAR_KIND_VIEWS }],
                },
            },
        },
    },
}
