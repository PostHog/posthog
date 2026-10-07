import { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import type { MockSignature } from '~/mocks/utils'

import { WarehouseHomeScene } from './WarehouseHomeScene'

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
            last_run_at: '2026-10-05T08:00:00Z',
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
            failed_at: '2026-10-05T04:15:00Z',
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
            failed_at: '2026-10-04T02:00:00Z',
            url: '/data-management/sources/2',
        },
        {
            id: '3',
            name: 'orders',
            type: 'materialized_view',
            status: 'degraded',
            error: null,
            failed_at: '2026-10-05T09:00:00Z',
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
        created_at: '2026-10-05T08:00:00Z',
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
        run('r2', 'customers', 'Stripe', 'Completed', '2026-10-05T07:30:00Z'),
        run('r3', 'orders', 'Materialized view', 'Completed', '2026-10-05T07:00:00Z'),
        run('r4', 'invoices', 'Stripe', 'Completed', '2026-10-05T06:00:00Z'),
        run('r5', 'charges', 'Stripe', 'Failed', '2026-10-05T04:15:00Z'),
    ],
}

const RUNNING_RUNS = {
    next: null,
    previous: null,
    results: [run('r1', 'subscriptions', 'Stripe', 'Running', null)],
}

interface Mocks {
    sources: MockSignature
    tables: MockSignature
    savedQueries: MockSignature
    health: MockSignature | 500
    completed: MockSignature | 500
    running: MockSignature | 500
}

function mocks({ sources, tables, savedQueries, health, completed, running }: Mocks): ReturnType<typeof mswDecorator> {
    const answer = (body: MockSignature | 500): MockSignature =>
        body === 500 ? (): [number, unknown] => [500, { detail: 'Server error' }] : body
    return mswDecorator({
        get: {
            '/api/projects/:team_id/external_data_sources': sources,
            '/api/environments/:team_id/external_data_sources': sources,
            '/api/projects/:team_id/warehouse_tables': tables,
            '/api/environments/:team_id/warehouse_tables': tables,
            '/api/projects/:team_id/warehouse_saved_queries': savedQueries,
            '/api/environments/:team_id/warehouse_saved_queries': savedQueries,
            '/api/projects/:team_id/data_warehouse/data_health_issues': answer(health),
            '/api/projects/:team_id/data_warehouse/completed_activity': answer(completed),
            '/api/projects/:team_id/data_warehouse/running_activity': answer(running),
        },
    })
}

const meta: Meta<typeof WarehouseHomeScene> = {
    title: 'Scenes-App/Data Warehouse/Warehouse home',
    component: WarehouseHomeScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [
            FEATURE_FLAGS.TODAY_RAIL_NAV,
            FEATURE_FLAGS.TODAY_RAIL_WAREHOUSE,
            FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION,
            FEATURE_FLAGS.SQL_EDITOR_BI_MODE,
        ],
    },
}
export default meta

const Template: StoryFn = () => <WarehouseHomeScene />

export const NewTeam = Template.bind({})
NewTeam.decorators = [
    mocks({
        sources: EMPTY_LIST,
        tables: EMPTY_LIST,
        savedQueries: EMPTY_LIST,
        health: { results: [], count: 0 },
        completed: EMPTY_ACTIVITY,
        running: EMPTY_ACTIVITY,
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
    }),
]

export const SectionErrors = Template.bind({})
SectionErrors.decorators = [
    mocks({
        sources: SOURCES,
        tables: TABLES,
        savedQueries: SAVED_QUERIES,
        health: 500,
        completed: 500,
        running: 500,
    }),
]
