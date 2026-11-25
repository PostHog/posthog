import { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockSignature } from '~/mocks/utils'

import { WarehouseOverviewScene } from './WarehouseOverviewScene'

const EMPTY_LIST = { results: [], count: 0, next: null, previous: null }
const EMPTY_ACTIVITY = { results: [], next: null, previous: null }

const SOURCES = {
    count: 1,
    results: [
        {
            id: '1',
            source_type: 'Stripe',
            prefix: null,
            status: 'Running',
            access_method: 'warehouse',
            last_run_at: '2026-11-24T08:00:00Z',
            schemas: [{ id: 's1', name: 'charges', should_sync: true, status: 'Completed' }],
        },
    ],
}

const TABLES = {
    count: 1,
    results: [{ id: 't1', name: 'stripe_charges', format: 'Parquet', external_data_source: { id: '1' }, columns: [] }],
}

const SAVED_QUERIES = {
    count: 1,
    results: [{ id: 'v1', name: 'orders', query: { kind: 'HogQLQuery', query: 'select 1' }, columns: [] }],
}

const ISSUES = {
    count: 4,
    results: [
        {
            id: '1',
            name: 'charges',
            type: 'external_data_sync',
            source_type: 'Stripe',
            sync_type: 'incremental',
            status: 'failed',
            error: 'Authentication error: expired API key',
            failed_at: '2026-11-24T04:15:00Z',
            url: '/data-management/sources/1',
        },
        {
            id: '2',
            name: 'example_table',
            type: 'external_data_sync',
            source_type: 'Postgres',
            sync_type: 'full_refresh',
            status: 'billing_limit',
            error: 'Billing limit reached for this period',
            failed_at: '2026-11-23T02:00:00Z',
            url: '/data-management/sources/2',
        },
        {
            id: '3',
            name: 'orders',
            type: 'materialized_view',
            status: 'degraded',
            error: null,
            failed_at: '2026-11-24T09:00:00Z',
            url: '/data-warehouse/view/3',
        },
        {
            // The endpoint answers for every pipeline, so this row must not render.
            id: '4',
            name: 'nightly_export',
            type: 'destination',
            status: 'failed',
            error: null,
            failed_at: null,
            url: null,
        },
    ],
}

const JOB_STATS = {
    days: 7,
    cutoff_time: '2026-11-17T09:00:00+00:00',
    total_jobs: 428,
    successful_jobs: 412,
    failed_jobs: 16,
    external_data_jobs: { total: 300, running: 2, successful: 288, failed: 12 },
    modeling_jobs: { total: 128, running: 0, successful: 124, failed: 4 },
    breakdown: {
        '2026-11-18': { successful: 60, failed: 2 },
        '2026-11-19': { successful: 58, failed: 5 },
        '2026-11-20': { successful: 62, failed: 1 },
        '2026-11-22': { successful: 70, failed: 4 },
        '2026-11-23': { successful: 80, failed: 0 },
        '2026-11-24': { successful: 82, failed: 4 },
    },
}

const NO_JOB_STATS = {
    days: 7,
    cutoff_time: '2026-11-17T09:00:00+00:00',
    total_jobs: 0,
    successful_jobs: 0,
    failed_jobs: 0,
    external_data_jobs: { total: 0, running: 0, successful: 0, failed: 0 },
    modeling_jobs: { total: 0, running: 0, successful: 0, failed: 0 },
    breakdown: {},
}

function run(
    id: string,
    name: string,
    type: string,
    status: string,
    finishedAt: string | null
): Record<string, unknown> {
    return {
        id,
        type,
        name,
        status,
        rows: finishedAt ? 1200 : 0,
        created_at: '2026-11-24T08:00:00Z',
        finished_at: finishedAt,
        latest_error: status === 'Failed' ? 'Authentication error: expired API key' : null,
        workflow_run_id: `wf-${id}`,
        origin: null,
        source_id: type === 'Materialized view' ? null : '1',
    }
}

const COMPLETED_RUNS = {
    next: null,
    previous: null,
    results: [
        run('r2', 'customers', 'Stripe', 'Completed', '2026-11-24T07:30:00Z'),
        run('r3', 'orders', 'Materialized view', 'Completed', '2026-11-24T07:00:00Z'),
        run('r4', 'invoices', 'Stripe', 'Completed', '2026-11-24T06:00:00Z'),
        run('r5', 'charges', 'Stripe', 'Failed', '2026-11-24T04:15:00Z'),
    ],
}

const RUNNING_RUNS = {
    next: null,
    previous: null,
    results: [run('r1', 'subscriptions', 'Stripe', 'Running', null)],
}

const READY_WAREHOUSE = {
    org_id: 'org-1',
    state: 'ready',
    status_message: 'Ready',
    s3_state: 'ready',
    metadata_store_state: 'ready',
    identity_state: 'ready',
    secrets_state: 'ready',
    ready_at: '2026-10-25T12:00:00Z',
    failed_at: null,
    trino: { state: 'ready', hoglake: false, connection: null },
    has_backfill: true,
    table_suffix: null,
    team_onboarded: true,
    schema_name: 'main',
}

const USAGE = {
    period_start: '2026-11-01',
    period_end: '2026-12-01',
    compute: {
        billable_bytes: 5 * 1024 ** 4,
        failed_billable_bytes: 0,
        logical_bytes: 5 * 1024 ** 4,
        queries: 240,
        free_bytes: 4 * 1024 ** 4,
        estimated_cost_usd: '6.250000',
    },
    storage: {
        gib_months: '50.000000',
        average_bytes: 50 * 1024 ** 3,
        free_gib_months: '100.000000',
        estimated_cost_usd: '0',
    },
    total_estimated_cost_usd: '6.25',
    forecast_total_usd: '9.80',
    daily: [],
    breakdown: [],
    budget: { monthly_budget_usd: null, share_used: null },
}

const WORKLOAD = {
    schema_version: 1,
    org_id: 'org-1',
    as_of: '2026-11-24T12:00:00Z',
    trino: { state: 'ready' },
    available: true,
    totals: { in_flight: 3, running: 2, queued: 1 },
    queries: [],
    queries_truncated: false,
}

const DATA_STATUS = {
    overall_readiness_state: 'up_to_date',
    events: { dataset: 'events', landing_state: 'in_sync', readiness_state: 'up_to_date' },
    persons: { dataset: 'persons', landing_state: 'in_sync', readiness_state: 'up_to_date' },
    sources: {
        readiness_state: 'up_to_date',
        detail: '',
        sources: [
            {
                source_id: '1',
                source_name: 'Stripe',
                source_type: 'Stripe',
                landing_counts: { in_sync: 7, behind: 1, failing: 0, not_in_warehouse: 0, paused: 0 },
            },
        ],
    },
}

interface Mocks {
    sources: MockSignature
    tables: MockSignature
    savedQueries: MockSignature
    health: MockSignature | 500
    completed: MockSignature | 500
    running: MockSignature | 500
    jobStats: MockSignature | 500
    usage?: MockSignature | 500
}

function mocks({
    sources,
    tables,
    savedQueries,
    health,
    completed,
    running,
    jobStats,
    usage = USAGE,
}: Mocks): ReturnType<typeof mswDecorator> {
    const answer = (body: MockSignature | 500): MockSignature =>
        body === 500 ? (): [number, unknown] => [500, { detail: 'Server error' }] : body
    return mswDecorator({
        get: {
            '/api/projects/:team_id/data_warehouse/warehouse_status/': READY_WAREHOUSE,
            '/api/projects/:team_id/managed_warehouse_console/usage/': answer(usage),
            '/api/projects/:team_id/data_warehouse/managed-warehouse-trino-monitoring/': WORKLOAD,
            '/api/projects/:team_id/data_warehouse/managed-warehouse-data-status/': DATA_STATUS,
            '/api/projects/:team_id/external_data_sources': sources,
            '/api/environments/:team_id/external_data_sources': sources,
            '/api/projects/:team_id/warehouse_tables': tables,
            '/api/environments/:team_id/warehouse_tables': tables,
            '/api/projects/:team_id/warehouse_saved_queries': savedQueries,
            '/api/environments/:team_id/warehouse_saved_queries': savedQueries,
            '/api/projects/:team_id/data_warehouse/data_health_issues': answer(health),
            '/api/projects/:team_id/data_warehouse/completed_activity': answer(completed),
            '/api/projects/:team_id/data_warehouse/running_activity': answer(running),
            '/api/projects/:team_id/data_warehouse/job_stats': answer(jobStats),
        },
    })
}

const meta: Meta<typeof WarehouseOverviewScene> = {
    title: 'Scenes-App/Data Warehouse/Warehouse overview',
    component: WarehouseOverviewScene,
    parameters: {
        layout: 'fullscreen',
        pageUrl: urls.warehouseOverview(),
        viewMode: 'story',
        mockDate: '2026-11-24T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE, FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION],
        testOptions: { waitForSelector: '[data-attr="warehouse-overview-recent-runs"]' },
    },
}
export default meta

const Template: StoryFn = () => <WarehouseOverviewScene />

export const NewTeam = Template.bind({})
NewTeam.decorators = [
    mocks({
        sources: EMPTY_LIST,
        tables: EMPTY_LIST,
        savedQueries: EMPTY_LIST,
        health: { results: [], count: 0 },
        completed: EMPTY_ACTIVITY,
        running: EMPTY_ACTIVITY,
        jobStats: NO_JOB_STATS,
    }),
]

export const Populated = Template.bind({})
Populated.decorators = [
    mocks({
        sources: SOURCES,
        tables: TABLES,
        savedQueries: SAVED_QUERIES,
        health: ISSUES,
        completed: COMPLETED_RUNS,
        running: RUNNING_RUNS,
        jobStats: JOB_STATS,
    }),
]

export const SectionErrors = Template.bind({})
SectionErrors.parameters = { testOptions: { waitForSelector: '[data-attr="warehouse-overview-runs-retry"]' } }
SectionErrors.decorators = [
    mocks({
        sources: SOURCES,
        tables: TABLES,
        savedQueries: SAVED_QUERIES,
        health: 500,
        completed: 500,
        running: 500,
        jobStats: 500,
        usage: 500,
    }),
]
