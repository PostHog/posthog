import type { Decorator, Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'

import type { DataModelingJobApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import type { ModelUsageApi, ModelUsageRowApi, ModelUsageTotalsApi } from './generated/api.schemas'
import { ModelsUsageTab } from './ModelsUsageTab'

const totals: ModelUsageTotalsApi = {
    runs: 320,
    measured_runs: 312,
    read_bytes: 8.4 * 1024 ** 4,
    read_rows: 24_000_000_000,
    cpu_microseconds: 5_400_000_000,
    query_count: 640,
}
const models: ModelUsageRowApi[] = [
    {
        ...totals,
        saved_query_id: '00000000-0000-4000-8000-000000000001',
        name: 'daily_order_summary',
        deleted: false,
        read_bytes: 5.1 * 1024 ** 4,
        read_rows: 14_000_000_000,
        cpu_microseconds: 3_200_000_000,
        query_count: 240,
        runs: 120,
        measured_runs: 118,
    },
    {
        ...totals,
        saved_query_id: '00000000-0000-4000-8000-000000000002',
        name: 'session_activity_by_account',
        deleted: false,
        read_bytes: 2.4 * 1024 ** 4,
        read_rows: 7_000_000_000,
        cpu_microseconds: 1_600_000_000,
        query_count: 288,
        runs: 144,
        measured_runs: 140,
    },
    {
        ...totals,
        saved_query_id: '00000000-0000-4000-8000-000000000003',
        name: 'weekly_revenue',
        deleted: false,
        read_bytes: 0.9 * 1024 ** 4,
        read_rows: 3_000_000_000,
        cpu_microseconds: 600_000_000,
        query_count: 112,
        runs: 56,
        measured_runs: 54,
    },
]
const populated: ModelUsageApi = {
    date_from: '2026-09-16',
    date_to: '2026-10-16',
    overview: totals,
    models,
    count: 3,
    usage_updated_at: '2026-10-16T03:00:00Z',
    trends: Array.from({ length: 30 }, (_, index) => ({
        ...totals,
        day: new Date(Date.UTC(2026, 8, 16 + index)).toISOString().slice(0, 10),
        read_bytes: (150 + ((index * 71) % 300)) * 1024 ** 3,
    })),
}
const unknown: ModelUsageTotalsApi = {
    runs: 8,
    measured_runs: 0,
    read_bytes: null,
    read_rows: null,
    cpu_microseconds: null,
    query_count: null,
}

const materializedViews = models.map((model) => ({
    id: model.saved_query_id,
    name: model.name,
    is_materialized: true,
}))

const jobTemplates: DataModelingJobApi[] = [
    {
        id: '10000000-0000-4000-8000-000000000001',
        saved_query_id: models[0].saved_query_id,
        status: 'Completed',
        engine: 'clickhouse',
        run_mode: 'incremental',
        full_refresh_reason: null,
        rows_materialized: 1_250_000,
        error: null,
        created_at: '2026-10-16T02:00:00Z',
        last_run_at: '2026-10-16T02:04:12Z',
        updated_at: '2026-10-16T02:04:12Z',
        workflow_id: 'materialize-example-1',
        workflow_run_id: 'run-example-1',
        rows_expected: 1_250_000,
        read_bytes: 640 * 1024 ** 3,
        read_rows: 2_400_000_000,
        cpu_microseconds: 410_000_000,
        query_count: 12,
        usage_updated_at: '2026-10-16T03:00:00Z',
    },
    {
        id: '10000000-0000-4000-8000-000000000002',
        saved_query_id: models[1].saved_query_id,
        status: 'Running',
        engine: 'managed_warehouse',
        run_mode: 'full_refresh',
        full_refresh_reason: 'definition_changed',
        rows_materialized: 840_000,
        error: null,
        created_at: '2026-10-16T01:30:00Z',
        last_run_at: '2026-10-16T01:30:00Z',
        updated_at: '2026-10-16T01:30:00Z',
        workflow_id: 'materialize-example-2',
        workflow_run_id: 'run-example-2',
        rows_expected: 2_100_000,
        read_bytes: null,
        read_rows: null,
        cpu_microseconds: null,
        query_count: null,
        usage_updated_at: null,
    },
    {
        id: '10000000-0000-4000-8000-000000000003',
        saved_query_id: models[2].saved_query_id,
        status: 'Failed',
        engine: 'clickhouse',
        run_mode: null,
        full_refresh_reason: null,
        rows_materialized: 0,
        error: 'Example materialization failure',
        created_at: '2026-10-15T23:00:00Z',
        last_run_at: '2026-10-15T23:01:30Z',
        updated_at: '2026-10-15T23:01:30Z',
        workflow_id: 'materialize-example-3',
        workflow_run_id: 'run-example-3',
        rows_expected: null,
        read_bytes: 48 * 1024 ** 3,
        read_rows: 180_000_000,
        cpu_microseconds: 32_000_000,
        query_count: 3,
        usage_updated_at: '2026-10-16T03:00:00Z',
    },
]

const jobs: DataModelingJobApi[] = Array.from({ length: 23 }, (_, index) => ({
    ...jobTemplates[index % jobTemplates.length],
    id: `10000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
    created_at: new Date(Date.UTC(2026, 9, 16, 2, -index * 15)).toISOString(),
}))

const inMainContent =
    (widthClass: string): Decorator =>
    (Story) => (
        <div className={`@container/main-content ${widthClass}`}>
            <Story />
        </div>
    )

const meta: Meta<typeof ModelsUsageTab> = {
    title: 'Products/Data modeling/Models usage',
    component: ModelsUsageTab,
    decorators: [mswDecorator({})],
    parameters: {
        featureFlags: [FEATURE_FLAGS.DATA_MODELING_USAGE, FEATURE_FLAGS.MANAGED_TRINO_QUERY],
        mockDate: '2026-10-16T04:00:00Z',
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/data_modeling_usage/': populated,
                    '/api/projects/:team_id/data_modeling_jobs/': ({ request }: MockResolverInfo) => {
                        const params = new URL(request.url).searchParams
                        const offset = Number(params.get('offset') ?? 0)
                        const limit = Number(params.get('limit') ?? 20)
                        const savedQueryId = params.get('saved_query_id')
                        const filteredJobs = savedQueryId
                            ? jobs.filter((job) => job.saved_query_id === savedQueryId)
                            : jobs

                        return [
                            200,
                            {
                                count: filteredJobs.length,
                                next: offset + limit < filteredJobs.length ? 'next' : null,
                                previous: offset > 0 ? 'previous' : null,
                                results: filteredJobs.slice(offset, offset + limit),
                            },
                        ]
                    },
                    '/api/projects/:team_id/warehouse_saved_queries/': {
                        count: materializedViews.length,
                        next: null,
                        previous: null,
                        results: materializedViews,
                    },
                },
            },
        },
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta
type Story = StoryObj<typeof ModelsUsageTab>

export const Populated: Story = { decorators: [inMainContent('w-256')] }
export const Narrow: Story = {
    decorators: [inMainContent('w-128')],
}
export const Unmeasured: Story = {
    decorators: [inMainContent('w-256')],
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/data_modeling_usage/': {
                        ...populated,
                        overview: unknown,
                        usage_updated_at: null,
                        trends: [],
                        count: 1,
                        models: [{ ...models[0], ...unknown }],
                    },
                },
            },
        },
    },
}
export const Empty: Story = {
    decorators: [inMainContent('w-256')],
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/data_modeling_usage/': {
                        ...populated,
                        overview: { ...unknown, runs: 0 },
                        models: [],
                        trends: [],
                        count: 0,
                        usage_updated_at: null,
                    },
                },
            },
        },
    },
}
export const Error: Story = {
    decorators: [inMainContent('w-256')],
    parameters: {
        msw: {
            mocks: {
                get: { '/api/projects/:team_id/data_modeling_usage/': () => [500, { detail: 'Example failure' }] },
            },
        },
    },
}
