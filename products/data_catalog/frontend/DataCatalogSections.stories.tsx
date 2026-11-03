import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DataCatalogScene } from './DataCatalogScene'

const nodes = [
    {
        id: 'orders-daily',
        name: 'orders_daily',
        type: 'matview',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        last_run_at: '2026-09-14T09:00:00Z',
        last_run_status: 'Failed',
        last_run_error: "Unknown column 'plan_tier' in the query.",
        sync_interval: '1hour',
        upstream_count: 0,
        downstream_count: 3,
        saved_query_id: 'query-orders-daily',
    },
    {
        id: 'revenue-by-account',
        name: 'revenue_by_account',
        type: 'matview',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        last_run_at: '2026-09-13T04:00:00Z',
        last_run_status: 'Failed',
        last_run_error: 'Memory limit exceeded while building the result.',
        suspended: {
            clickhouse: { at: '2026-09-13T04:00:00Z', reason: 'Memory limit exceeded.', job_id: 'job-1' },
        },
        sync_interval: '24hour',
        upstream_count: 0,
        downstream_count: 0,
        saved_query_id: 'query-revenue-by-account',
    },
    {
        id: 'active-users-weekly',
        name: 'active_users_weekly',
        type: 'matview',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        last_run_at: '2026-09-14T23:00:00Z',
        last_run_status: 'Completed',
        last_run_error: null,
        sync_interval: '24hour',
        upstream_count: 0,
        downstream_count: 0,
        saved_query_id: 'query-active-users-weekly',
    },
]

const savedQueries = {
    results: nodes.map(({ saved_query_id, name }) => ({
        id: saved_query_id,
        name,
        columns: [],
        is_materialized: true,
    })),
    count: nodes.length,
}

const checks = [
    {
        id: 'check-events',
        name: 'row_count_drop',
        check_type: 'row_count',
        subject_type: 'posthog_table',
        subject_name: 'events',
        subject_node_id: null,
        last_status: 'failed',
        failing_since: '2026-09-14T18:00:00Z',
    },
]

const certifications = [
    {
        id: 'cert-1',
        table: null,
        saved_query: 'query-orders-daily',
        target_type: 'view',
        target_name: 'orders_daily',
        status: 'proposed',
        proposed_status: 'certified',
        certified_by: null,
        certified_at: null,
        created_by: null,
        created_at: '2026-09-14T00:00:00Z',
    },
]

const owner = { id: 1, uuid: 'user-1', first_name: 'Ada', last_name: 'Lane', email: 'ada@example.com' }

const metrics = [
    {
        id: 'metric-1',
        name: 'weekly_active_accounts',
        display_name: 'Weekly active accounts',
        description: 'Accounts with at least one **pageview** in the last 7 days.',
        definition_kind: 'HogQLQuery',
        status: 'approved',
        is_drifted: false,
        created_source: 'user',
        owner: 'ada@example.com',
        created_by: owner,
        created_at: '2026-09-01T10:00:00Z',
    },
    {
        id: 'metric-2',
        name: 'trial_conversion_rate',
        display_name: 'Trial conversion rate',
        description: 'Share of trials that convert to a paid plan within 30 days.',
        definition_kind: 'InsightVizNode',
        status: 'proposed',
        is_drifted: false,
        created_source: 'ai_generated',
        confidence: 0.82,
        ai_model: 'example-model',
        reasoning: 'Trials and upgrades share an account id.',
        owner: null,
        created_by: owner,
        created_at: '2026-09-10T10:00:00Z',
        source_insight_short_id: 'abc123',
    },
    {
        id: 'metric-3',
        name: 'net_revenue_retention',
        display_name: '',
        description: '',
        definition_kind: 'HogQLQuery',
        status: 'proposed',
        is_drifted: true,
        created_source: 'user',
        owner: 'ada@example.com',
        created_by: owner,
        created_at: '2026-09-12T10:00:00Z',
        source_insight_short_id: 'def456',
    },
]

const proposals = [
    {
        id: 'proposal-1',
        source_table_name: 'events',
        source_table_key: 'properties.account_id',
        joining_table_name: 'stripe_customers',
        joining_table_key: 'metadata.account_id',
        field_name: 'stripe_customer',
        confidence: 0.91,
        reasoning: 'Both columns hold the same account id format.',
        evidence: { matched_rows: 1200, sample_size: 1300 },
        status: 'pending',
        reviewed_by: null,
        reviewed_at: null,
        rejection_reason: '',
        created_join: null,
        created_by: null,
        created_at: '2026-09-14T00:00:00Z',
    },
    {
        id: 'proposal-2',
        source_table_name: 'orders_daily',
        source_table_key: 'customer_id',
        joining_table_name: 'hubspot_contacts',
        joining_table_key: 'id',
        field_name: 'contact',
        confidence: 0.4,
        reasoning: 'The ids look alike but rarely match.',
        status: 'rejected',
        reviewed_by: owner,
        reviewed_at: '2026-09-14T00:00:00Z',
        rejection_reason: 'These ids come from different systems.',
        created_join: null,
        created_by: null,
        created_at: '2026-09-13T00:00:00Z',
    },
]

const viewLinks = [
    {
        id: 'join-1',
        source_table_name: 'events',
        source_table_key: 'person_id',
        joining_table_name: 'persons',
        joining_table_key: 'id',
        field_name: 'person',
    },
]

function schemaTable(name: string, columns: Record<string, string>): Record<string, unknown> {
    return {
        type: 'posthog',
        id: name,
        name,
        fields: Object.fromEntries(
            Object.entries(columns).map(([column, type]) => [
                column,
                { name: column, hogql_value: column, type, schema_valid: true },
            ])
        ),
    }
}

const databaseTables = Object.fromEntries(
    [
        schemaTable('events', { person_id: 'string', distinct_id: 'string', properties: 'json' }),
        schemaTable('persons', { id: 'string', created_at: 'datetime', properties: 'json' }),
    ].map((table) => [table.name as string, table])
)

const joinValidation = {
    is_valid: true,
    msg: null,
    hogql: null,
    columns: ['source_key', 'joining_key'],
    results: [
        ['person-1', 'person-1'],
        ['person-2', 'person-2'],
    ],
    total_rows: 1300,
    matched_rows: 1240,
    match_rate: 0.95,
}

async function openJoinEditor(canvasElement: HTMLElement): Promise<void> {
    const menuTrigger = await waitFor(() => {
        const trigger = canvasElement.querySelector<HTMLButtonElement>(
            '[data-attr="data-catalog-relationships-row-actions"]'
        )
        if (!trigger) {
            throw new Error('Join row not rendered yet')
        }
        return trigger
    })
    menuTrigger.click()
    const editItem = await waitFor(() => {
        const item = document.querySelector<HTMLElement>('[data-attr="data-catalog-relationships-edit-join"]')
        if (!item) {
            throw new Error('Join menu not open yet')
        }
        return item
    })
    editItem.click()
    await waitFor(() => {
        if (!document.querySelector('[data-attr="data-catalog-join-editor"]')) {
            throw new Error('Join editor not open yet')
        }
    })
}

const inMainContent =
    (widthClass: string): Decorator =>
    (Story) => (
        <div className={`@container/main-content ${widthClass}`}>
            <Story />
        </div>
    )

const meta: Meta<typeof DataCatalogScene> = {
    title: 'Products/Data catalog/Sections',
    component: DataCatalogScene,
    beforeEach: () => {
        const context = window.POSTHOG_APP_CONTEXT!
        const previous = context.resource_access_control
        context.resource_access_control = {
            ...previous,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.Editor,
        }
        return () => {
            context.resource_access_control = previous
        }
    },
    decorators: [mswDecorator({}), inMainContent('w-256')],
    parameters: {
        pageUrl: urls.dataCatalog(),
        mockDate: '2026-09-15',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/data_modeling_nodes/': { results: nodes, count: nodes.length },
                    '/api/environments/:team_id/data_modeling_edges/': { results: [], count: 0 },
                    '/api/environments/:team_id/warehouse_saved_queries/': savedQueries,
                    '/api/projects/:team_id/warehouse_saved_queries/': savedQueries,
                    '/api/projects/:team_id/data_quality_checks/': { results: checks, count: checks.length },
                    '/api/projects/:team_id/data_quality_checks/health/': [],
                    '/api/projects/:team_id/data_quality_checks/schedules/': [],
                    '/api/projects/:team_id/data_catalog/certifications/': {
                        results: certifications,
                        count: certifications.length,
                    },
                    '/api/projects/:team_id/data_catalog/relationship_proposals/': {
                        results: proposals,
                        count: 1,
                    },
                    '/api/projects/:team_id/data_catalog/metrics/': { results: metrics, count: metrics.length },
                    '/api/projects/:team_id/warehouse_view_links/': { results: viewLinks, count: viewLinks.length },
                    '/api/organizations/:organization_id/members/': {
                        results: [{ id: 'member-1', user: owner, level: 8 }],
                        count: 1,
                    },
                },
                post: {
                    '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                        const { query } = (await request.json()) as { query: { kind: string } }
                        return query.kind === NodeKind.DatabaseSchemaQuery
                            ? [200, { tables: databaseTables, joins: [] }]
                            : [200, {}]
                    },
                    '/api/projects/:team_id/warehouse_view_link/validate/': joinValidation,
                },
            },
        },
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof DataCatalogScene>

export const Overview: Story = {}

export const OverviewNarrow: Story = {
    decorators: [inMainContent('w-128')],
}

export const OverviewWithoutWarehouseAccess: Story = {
    beforeEach: () => {
        const context = window.POSTHOG_APP_CONTEXT!
        const previous = context.resource_access_control
        context.resource_access_control = {
            ...previous,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.None,
        }
        return () => {
            context.resource_access_control = previous
        }
    },
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText('Access denied')
    },
}

export const Metrics: Story = {
    parameters: { pageUrl: urls.dataCatalog('metrics') },
}

export const MetricsNarrow: Story = {
    parameters: { pageUrl: urls.dataCatalog('metrics') },
    decorators: [inMainContent('w-128')],
}

export const Relationships: Story = {
    parameters: { pageUrl: urls.dataCatalog('relationships') },
}

export const RelationshipsNarrow: Story = {
    parameters: { pageUrl: urls.dataCatalog('relationships') },
    decorators: [inMainContent('w-128')],
}

export const RelationshipsEditJoin: Story = {
    parameters: { pageUrl: urls.dataCatalog('relationships') },
    play: async ({ canvasElement }) => openJoinEditor(canvasElement),
}
