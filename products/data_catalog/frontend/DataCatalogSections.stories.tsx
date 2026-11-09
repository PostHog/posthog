import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
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
                    '/api/projects/:team_id/data_catalog/relationship_proposals/': { results: [], count: 3 },
                    '/api/projects/:team_id/data_catalog/metrics/': { results: [], count: 0 },
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

const suggestedMaterialization = {
    id: 'suggestion-1',
    kind: 'materialize',
    subject_kind: 'saved_query',
    subject_id: 'query-active-users-weekly',
    payload: {
        subject_name: 'active_users_weekly',
        refresh_interval_seconds: 86400,
        saves_seconds_per_month: 3600,
        saves_bytes_per_month: 0,
        freshness_today_seconds: 3600,
        freshness_after_seconds: 90000,
        live_sources: { names: ['events'], hidden_count: 0 },
        unknown_sources: { names: [], hidden_count: 0 },
        refresh_interval_basis: 'source_sync',
        refresh_mode: 'full',
    },
    payload_version: 1,
    evidence: { human_requests: 120, human_users: 4, human_days: 20, requests_by_surface: { sql_editor: 120 } },
    evidence_window_start: '2026-08-15T00:00:00Z',
    evidence_window_end: '2026-09-15T00:00:00Z',
    last_seen_at: '2026-09-15T00:00:00Z',
    status: 'proposed',
    surfaced_at: '2026-09-15T00:00:00Z',
    can_act: true,
}

export const OverviewWithSuggestions: Story = {
    parameters: {
        featureFlags: [
            FEATURE_FLAGS.TODAY_RAIL_NAV,
            FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE,
            FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS,
        ],
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/warehouse_suggestions/': { results: [suggestedMaterialization], count: 1 },
                    '/api/projects/:team_id/warehouse_suggestions/status/': {
                        enabled: true,
                        eligible: true,
                        days_with_data: 30,
                        window_days: 30,
                        paused_reason: null,
                        refreshed_at: '2026-09-15T00:00:00Z',
                    },
                },
            },
        },
    },
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

export const OverviewWithoutWarehouseAccessNarrow: Story = {
    ...OverviewWithoutWarehouseAccess,
    decorators: [inMainContent('w-128')],
}
