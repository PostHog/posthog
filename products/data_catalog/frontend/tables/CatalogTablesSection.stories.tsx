import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'
import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DataCatalogScene } from '../DataCatalogScene'

function posthogTable(name: string): Record<string, unknown> {
    return { type: 'posthog', id: name, name, fields: {} }
}

function sourceTable(id: string, name: string, sourceType: string, lastSyncedAt: string): Record<string, unknown> {
    return {
        type: 'data_warehouse',
        id,
        name,
        fields: {},
        format: 'Parquet',
        url_pattern: '',
        source: { id: `source-${sourceType}`, source_type: sourceType, status: 'Completed', prefix: '' },
        schema: { id: `schema-${id}`, name, should_sync: true, incremental: true, last_synced_at: lastSyncedAt },
    }
}

function selfManagedTable(id: string, name: string): Record<string, unknown> {
    return { type: 'data_warehouse', id, name, fields: {}, format: 'Parquet', url_pattern: 's3://example-bucket/*' }
}

function view(id: string, name: string): Record<string, unknown> {
    return { type: 'view', id, name, fields: {}, query: { kind: 'HogQLQuery', query: 'select 1' } }
}

const databaseTables = Object.fromEntries(
    [
        posthogTable('events'),
        posthogTable('persons'),
        posthogTable('sessions'),
        sourceTable('table-charges', 'stripe.charges', 'Stripe', '2026-09-14T20:10:00Z'),
        sourceTable('table-contacts', 'hubspot.contacts', 'Hubspot', '2026-09-14T23:00:00Z'),
        selfManagedTable('table-orders-export', 'orders_export'),
        view('query-revenue', 'revenue_by_account'),
        view('query-orders', 'orders_daily'),
        view('query-marketing', 'marketing_spend'),
        view('query-active', 'active_users_weekly'),
        view('query-adoption', 'feature_adoption'),
    ].map((table) => [table.name as string, table])
)

function node(savedQueryId: string, name: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        id: `node-${savedQueryId}`,
        name,
        type: 'matview',
        saved_query_id: savedQueryId,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        last_run_at: '2026-09-14T23:00:00Z',
        last_run_status: 'Completed',
        last_run_error: null,
        sync_interval: '24hour',
        upstream_count: 1,
        downstream_count: 0,
        ...overrides,
    }
}

const nodes = [
    node('query-revenue', 'revenue_by_account', {
        last_run_at: '2026-09-13T04:00:00Z',
        last_run_status: 'Failed',
        last_run_error: 'Memory limit exceeded while building the result.',
        suspended: {
            clickhouse: { at: '2026-09-13T04:00:00Z', reason: 'Memory limit exceeded.', job_id: 'job-1' },
        },
        downstream_count: 4,
    }),
    node('query-orders', 'orders_daily', {
        last_run_at: '2026-09-14T09:00:00Z',
        last_run_status: 'Failed',
        last_run_error: "Unknown column 'plan_tier' in the query.",
        sync_interval: '1hour',
        downstream_count: 3,
    }),
    node('query-marketing', 'marketing_spend', { last_run_at: '2026-09-12T23:00:00Z' }),
    node('query-active', 'active_users_weekly'),
    node('query-adoption', 'feature_adoption', { type: 'view', sync_interval: undefined, last_run_at: null }),
]

const savedQueries = nodes.map((entry) => ({
    id: entry.saved_query_id,
    name: entry.name,
    columns: [],
    is_materialized: entry.type === 'matview',
    origin: 'data_warehouse',
    managed_viewset_kind: null,
    last_run_at: entry.last_run_at,
    status: entry.last_run_status,
}))

function check(
    id: string,
    subjectType: string,
    subjectUuid: string,
    subjectName: string,
    lastStatus: string
): Record<string, unknown> {
    return {
        id,
        name: id,
        check_type: 'not_null',
        column_name: 'id',
        severity: 'error',
        enabled: true,
        subject_type: subjectType,
        subject_uuid: subjectUuid,
        subject_name: subjectName,
        subject_node_id: null,
        last_status: lastStatus,
        last_run_at: '2026-09-14T18:00:00Z',
        failing_since: lastStatus === 'passed' ? null : '2026-09-14T18:00:00Z',
    }
}

const checks = [
    check('events arrive every hour', 'posthog_table', 'posthog-events', 'events', 'failed'),
    check('charge id is never null', 'table', 'table-charges', 'stripe.charges', 'passed'),
    check('amount is positive', 'table', 'table-charges', 'stripe.charges', 'passed'),
    check('account id is unique', 'view', 'query-revenue', 'revenue_by_account', 'failed'),
    check('revenue is never negative', 'view', 'query-revenue', 'revenue_by_account', 'errored'),
    check('mrr is filled in', 'view', 'query-revenue', 'revenue_by_account', 'passed'),
    check('order id is unique', 'view', 'query-orders', 'orders_daily', 'passed'),
    check('weekly users above zero', 'view', 'query-active', 'active_users_weekly', 'passed'),
]

function certification(
    id: string,
    savedQuery: string,
    targetName: string,
    status: string,
    proposedStatus: string = status === 'proposed' ? 'certified' : status
): Record<string, unknown> {
    return {
        id,
        table: null,
        saved_query: savedQuery,
        target_type: 'view',
        target_name: targetName,
        status,
        proposed_status: proposedStatus,
        notes: '',
        certified_by: null,
        certified_at: null,
        created_by: null,
        created_at: '2026-09-01T00:00:00Z',
    }
}

const certifications = [
    certification('cert-revenue', 'query-revenue', 'revenue_by_account', 'certified'),
    certification('cert-orders', 'query-orders', 'orders_daily', 'proposed'),
    certification('cert-active', 'query-active', 'active_users_weekly', 'certified'),
    certification('cert-marketing', 'query-marketing', 'marketing_spend', 'proposed', 'deprecated'),
    certification('cert-adoption', 'query-adoption', 'feature_adoption', 'deprecated'),
]

const RUN_HISTORY_STATUSES: Record<string, string[]> = {
    'query-revenue': ['Failed', 'Failed', 'Failed', 'Failed', 'Completed'],
    'query-orders': ['Failed', 'Completed', 'Completed', 'Completed', 'Completed'],
}

function runHistoryFor(savedQueryId: string): Record<string, unknown> {
    const statuses = RUN_HISTORY_STATUSES[savedQueryId] ?? Array(5).fill('Completed')
    return {
        run_history: statuses.map((status, index) => ({
            status,
            timestamp: `2026-09-14T${String(20 - index).padStart(2, '0')}:00:00Z`,
        })),
    }
}

const runningSuiteRun = {
    id: 'suite-run-1',
    trigger: 'manual',
    status: 'running',
    subject_type: null,
    subject_uuid: null,
    workflow_id: 'workflow-1',
    checks_passed: 0,
    checks_failed: 0,
    checks_errored: 0,
    checks_skipped: 0,
    started_at: '2026-09-15T00:00:00Z',
    finished_at: null,
}

function mocks({ databaseFails = false }: { databaseFails?: boolean } = {}): Mocks {
    return {
        get: {
            '/api/environments/:team_id/data_modeling_nodes/': { results: nodes, count: nodes.length },
            '/api/environments/:team_id/data_modeling_edges/': { results: [], count: 0 },
            '/api/environments/:team_id/warehouse_saved_queries/': {
                results: savedQueries,
                count: savedQueries.length,
            },
            '/api/projects/:team_id/warehouse_saved_queries/': { results: savedQueries, count: savedQueries.length },
            '/api/environments/:team_id/warehouse_saved_queries/:id/run_history/': ({ params }) => [
                200,
                runHistoryFor(params.id as string),
            ],
            '/api/projects/:team_id/data_quality_checks/': { results: checks, count: checks.length },
            '/api/projects/:team_id/data_quality_checks/health/': [],
            '/api/projects/:team_id/data_quality_checks/schedules/': [],
            '/api/projects/:team_id/data_quality_checks/subjects/': [
                { subject_type: 'posthog_table', id: 'posthog-events', name: 'events', display_name: '' },
            ],
            '/api/projects/:team_id/data_catalog/certifications/': {
                results: certifications,
                count: certifications.length,
            },
            '/api/projects/:team_id/data_quality_runs/:id/': runningSuiteRun,
            '/api/projects/:team_id/data_catalog/relationship_proposals/': { results: [], count: 0 },
            '/api/projects/:team_id/data_catalog/metrics/': { results: [], count: 0 },
        },
        post: {
            '/api/projects/:team_id/data_quality_runs/': runningSuiteRun,
            '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                const { query } = (await request.json()) as { query: { kind: string } }
                if (query.kind !== NodeKind.DatabaseSchemaQuery) {
                    return [200, {}]
                }
                return databaseFails ? [500, { detail: 'Server error' }] : [200, { tables: databaseTables, joins: [] }]
            },
        },
    }
}

const inMainContent =
    (widthClass: string): Decorator =>
    (Story) => (
        <div className={`@container/main-content ${widthClass} max-w-full`}>
            <Story />
        </div>
    )

const meta: Meta<typeof DataCatalogScene> = {
    title: 'Products/Data catalog/Tables and views',
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
        pageUrl: urls.dataCatalog('tables'),
        mockDate: '2026-09-15',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
        msw: { mocks: mocks() },
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof DataCatalogScene>

async function expandRow(canvasElement: HTMLElement, name: string): Promise<void> {
    const toggle = await waitFor(() => {
        const button = canvasElement.querySelector<HTMLButtonElement>(`button[aria-label="Show checks for ${name}"]`)
        if (!button) {
            throw new Error('Row not rendered yet')
        }
        return button
    })
    toggle.click()
    await waitFor(() => {
        if (!canvasElement.querySelector('[data-attr="data-catalog-tables-add-check"]')) {
            throw new Error('Row not expanded yet')
        }
    })
}

export const AllTables: Story = {}

export const Narrow: Story = {
    decorators: [inMainContent('w-128')],
}

export const RowExpanded: Story = {
    play: async ({ canvasElement }) => expandRow(canvasElement, 'revenue_by_account'),
}

export const ProposedCertifications: Story = {
    parameters: {
        pageUrl: combineUrl(urls.dataCatalog('tables'), { filter: 'proposed' }).url,
    },
}

export const LoadError: Story = {
    parameters: { msw: { mocks: mocks({ databaseFails: true }) } },
}

export const RunningAllChecks: Story = {
    play: async ({ canvasElement }) => {
        const runAll = await waitFor(() => {
            const button = canvasElement.querySelector<HTMLButtonElement>('[data-attr="data-catalog-tables-run-all"]')
            if (!button || button.getAttribute('aria-disabled') === 'true') {
                throw new Error('Run all checks not ready yet')
            }
            return button
        })
        runAll.click()
        await waitFor(() => {
            if (runAll.getAttribute('aria-busy') !== 'true') {
                throw new Error('Run not started yet')
            }
        })
    },
}

async function selectRows(canvasElement: HTMLElement, names: string[]): Promise<void> {
    for (const name of names) {
        const checkbox = await waitFor(() => {
            const element = canvasElement.querySelector<HTMLElement>(`[aria-label="Select ${name}"]`)
            if (!element) {
                throw new Error('Row not rendered yet')
            }
            return element
        })
        checkbox.click()
    }
    await waitFor(() => {
        if (!canvasElement.querySelector('[data-attr="data-catalog-tables-bulk-bar"]')) {
            throw new Error('Bulk bar not shown yet')
        }
    })
}

export const RowsSelected: Story = {
    play: async ({ canvasElement }) => selectRows(canvasElement, ['orders_daily', 'marketing_spend', 'events']),
}

export const NarrowRowsSelected: Story = {
    decorators: [inMainContent('w-128')],
    play: RowsSelected.play,
}
