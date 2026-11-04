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

const certificationSuggestion = (id: string, kind: 'certify' | 'deprecate', name: string): Record<string, unknown> => ({
    id,
    kind,
    subject_kind: 'saved_query',
    subject_id: `subject-${id}`,
    payload:
        kind === 'certify'
            ? { subject_name: name }
            : { subject_name: name, refresh_seconds_per_month: 5400, refresh_bytes_per_month: 2 * 10 ** 12 },
    payload_version: 1,
    evidence: { human_requests: 640, human_users: 9, human_days: 28, requests_by_surface: { dashboard: 640 } },
    evidence_window_start: '2026-08-15T00:00:00Z',
    evidence_window_end: '2026-09-14T00:00:00Z',
    last_seen_at: '2026-09-14T08:30:00Z',
    status: 'proposed',
    surfaced_at: '2026-09-14T08:30:00Z',
    reviewed_by: null,
    reviewed_at: null,
    dismissal_reason: null,
    dismissal_note: null,
    created_asset: null,
    asset_outcome: null,
    realized_seconds_saved_per_month: null,
    realized_bytes_saved_per_month: null,
    can_act: true,
    assignee: null,
})

const certificationSuggestions = [
    certificationSuggestion('1', 'certify', 'customer_monthly_revenue'),
    certificationSuggestion('2', 'certify', 'orders_daily'),
    certificationSuggestion('3', 'deprecate', 'old_marketing_rollup'),
]

export const OverviewWithCertificationSuggestions: Story = {
    parameters: {
        featureFlags: [
            FEATURE_FLAGS.TODAY_RAIL_NAV,
            FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE,
            FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS,
        ],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/warehouse_suggestions/': {
                    results: certificationSuggestions,
                    count: certificationSuggestions.length,
                },
                '/api/projects/:team_id/warehouse_suggestions/status/': {
                    enabled: true,
                    eligible: true,
                    days_with_data: 30,
                    window_days: 30,
                    paused_reason: null,
                    refreshed_at: '2026-09-14T08:30:00Z',
                },
            },
        }),
    ],
}

export const Lineage: Story = {
    parameters: { pageUrl: urls.dataCatalog('lineage') },
}
