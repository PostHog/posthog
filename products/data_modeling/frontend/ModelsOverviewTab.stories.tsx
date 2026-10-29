import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ModelsOverviewTab } from './ModelsOverviewTab'

const NODES_URL = '/api/environments/:team_id/data_modeling_nodes/'
const CHECKS_URL = '/api/projects/:team_id/data_quality_checks/'
const SUGGESTIONS_URL = '/api/projects/:team_id/warehouse_suggestions/'
const SUGGESTIONS_STATUS_URL = '/api/projects/:team_id/warehouse_suggestions/status/'

function savedQueriesFor(rows: { id: string; name: string }[]): Record<string, unknown> {
    const results = rows.map(({ id, name }) => ({ id: `query-${id}`, name, columns: [], is_materialized: true }))
    return { results, count: results.length }
}

function savedQueryMocks(rows: { id: string; name: string }[]): Mocks['get'] {
    return {
        '/api/environments/:team_id/warehouse_saved_queries/': savedQueriesFor(rows),
        '/api/projects/:team_id/warehouse_saved_queries/': savedQueriesFor(rows),
    }
}

const nodes = ['attention', 'behind'].flatMap((group) =>
    Array.from({ length: 12 }, (_, index) => ({
        id: `${group}-${index + 1}`,
        name: `${group}_model_${index + 1}`,
        type: 'matview',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        last_run_at: '2026-09-14T00:00:00Z',
        last_run_status: group === 'attention' ? 'Failed' : 'Completed',
        last_run_error: group === 'attention' ? 'Example refresh failed.' : null,
        sync_interval: '1hour',
        upstream_count: 0,
        downstream_count: 0,
        saved_query_id: `query-${group}-${index + 1}`,
    }))
)
const checks = Array.from({ length: 12 }, (_, index) => ({
    id: `check-${index + 1}`,
    name: `Example check ${index + 1}`,
    check_type: 'not_null',
    subject_type: 'view',
    subject_name: `example_view_${index + 1}`,
    subject_node_id: `attention-${index + 1}`,
    last_status: 'failed',
}))

const healthyNodes = Array.from({ length: 3 }, (_, index) => ({
    id: `healthy-${index + 1}`,
    name: `healthy_model_${index + 1}`,
    type: 'matview',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    last_run_at: '2026-09-15T00:00:00Z',
    last_run_status: 'Completed',
    last_run_error: null,
    sync_interval: '24hour',
    upstream_count: 0,
    downstream_count: 0,
    saved_query_id: `query-healthy-${index + 1}`,
}))
const passingChecks = [
    {
        id: 'check-1',
        name: 'Example check',
        check_type: 'not_null',
        subject_type: 'view',
        subject_name: 'example_view',
        subject_node_id: 'healthy-1',
        last_status: 'passed',
    },
]
const neverRunChecks = passingChecks.map((check) => ({ ...check, last_status: '' }))

const suggestionStatus = {
    enabled: true,
    eligible: true,
    days_with_data: 30,
    window_days: 30,
    paused_reason: null,
    refreshed_at: '2026-09-15T00:00:00Z',
}

function suggestion(id: string, name: string, kind: 'materialize' | 'unmaterialize', savedSeconds: number): object {
    const payload =
        kind === 'materialize'
            ? {
                  subject_name: name,
                  refresh_interval_seconds: 86400,
                  saves_seconds_per_month: savedSeconds,
                  saves_bytes_per_month: 0,
                  freshness_today_seconds: 3600,
                  freshness_after_seconds: 90000,
                  live_sources: { names: ['events'], hidden_count: 0 },
                  unknown_sources: { names: [], hidden_count: 0 },
                  refresh_interval_basis: 'source_sync',
                  refresh_mode: 'full',
              }
            : {
                  subject_name: name,
                  refresh_seconds_per_month: savedSeconds * 2,
                  refresh_bytes_per_month: 0,
                  live_seconds_per_month: savedSeconds,
                  live_bytes_per_month: 0,
                  read_seconds: 3.6,
              }
    return {
        id,
        kind,
        subject_kind: 'saved_query',
        subject_id: `view-${id}`,
        payload,
        payload_version: 1,
        evidence: { human_requests: 214, human_users: 6, human_days: 27, requests_by_surface: { sql_editor: 214 } },
        evidence_window_start: '2026-08-15T00:00:00Z',
        evidence_window_end: '2026-09-15T00:00:00Z',
        last_seen_at: '2026-09-15T00:00:00Z',
        status: 'proposed',
        surfaced_at: '2026-09-15T00:00:00Z',
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
    }
}

const suggestions = [
    suggestion('1', 'customer_monthly_revenue', 'materialize', 2400),
    suggestion('2', 'sessions_by_plan_daily', 'materialize', 1080),
    suggestion('3', 'legacy_signup_funnel', 'unmaterialize', 1800),
    suggestion('4', 'product_usage_rollup', 'materialize', 600),
]

function healthyMocks(checkRows: Record<string, any>[], extra: Mocks['get'] = {}): { mocks: Mocks } {
    return {
        mocks: {
            get: {
                [NODES_URL]: { results: healthyNodes, count: healthyNodes.length },
                ...savedQueryMocks(healthyNodes),
                [CHECKS_URL]: { results: checkRows, count: checkRows.length },
                ...extra,
            },
        },
    }
}

const suggestionMocks: Mocks['get'] = {
    [SUGGESTIONS_URL]: { results: suggestions, count: suggestions.length },
    [SUGGESTIONS_STATUS_URL]: suggestionStatus,
}

const inMainContent =
    (widthClass: string): Decorator =>
    (Story) => (
        <div className={`@container/main-content ${widthClass}`}>
            <Story />
        </div>
    )

const meta: Meta<typeof ModelsOverviewTab> = {
    title: 'Products/Data modeling/Models overview',
    component: ModelsOverviewTab,
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
        pageUrl: urls.models(),
        mockDate: '2026-09-15',
        msw: {
            mocks: {
                get: {
                    [NODES_URL]: { results: nodes, count: nodes.length },
                    '/api/environments/:team_id/data_modeling_edges/': { results: [], count: 0 },
                    ...savedQueryMocks(nodes),
                    [CHECKS_URL]: { results: checks, count: checks.length },
                    '/api/projects/:team_id/data_quality_checks/health/': [],
                },
            },
        },
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof ModelsOverviewTab>
export const Paginated: Story = {}
export const Narrow: Story = {
    decorators: [inMainContent('w-128')],
}

export const PartialLastPage: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('1–10 of 24')
        await canvas.findByText('1–10 of 12')
        const tables = [
            { section: 'attention', lastPage: '21–24 of 24' },
            { section: 'failing-checks', lastPage: '11–12 of 12' },
        ].map(({ section, lastPage }) => {
            const table = canvasElement.querySelector<HTMLElement>(`[data-attr="models-overview-${section}"]`)!
            return { table, lastPage, height: table.offsetHeight, top: table.getBoundingClientRect().top }
        })
        for (const { table, lastPage } of tables) {
            while (!within(table).queryByText(lastPage)) {
                fireEvent.click(within(table).getByRole('button', { name: 'Go to next page' }))
                await waitFor(() => within(table).getByRole('button', { name: 'Go to next page' }))
            }
        }
        await waitFor(() => {
            for (const initial of tables) {
                if (
                    initial.table.offsetHeight !== initial.height ||
                    initial.table.getBoundingClientRect().top !== initial.top
                ) {
                    throw new Error('Paging must preserve table heights and the positions of surrounding sections')
                }
            }
        })
    },
}
export const NarrowPartialLastPage: Story = {
    ...Narrow,
    play: PartialLastPage.play,
}

export const Healthy: Story = {
    parameters: { msw: healthyMocks(passingChecks) },
}

export const HealthyWithoutChecks: Story = {
    parameters: { msw: healthyMocks([]) },
}

export const HealthyWithChecksNotRun: Story = {
    parameters: { msw: healthyMocks(neverRunChecks) },
}

export const HealthyWithDataQualityDisabled: Story = {
    parameters: { featureFlags: [], msw: healthyMocks(passingChecks) },
}

export const HealthyNarrow: Story = {
    decorators: [inMainContent('w-128')],
    parameters: { msw: healthyMocks(passingChecks) },
}

export const WithSuggestions: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS],
        msw: {
            mocks: {
                ...healthyMocks(passingChecks, suggestionMocks).mocks,
                post: { '/api/projects/:team_id/warehouse_suggestions/:id/dismiss/': { status: 'dismissed' } },
            },
        },
        testOptions: { waitForSelector: '[data-attr="models-overview-suggestions-review-all"]' },
    },
}

export const WithSuggestionsNarrow: Story = {
    ...WithSuggestions,
    decorators: [inMainContent('w-128')],
}

export const ChecksFailedToLoad: Story = {
    parameters: { msw: healthyMocks([], { [CHECKS_URL]: () => [500, { detail: 'Server error' }] }) },
}

export const ModelsFailedToLoad: Story = {
    parameters: { msw: healthyMocks(passingChecks, { [NODES_URL]: () => [500, { detail: 'Server error' }] }) },
}

export const NoModelsWithFailingCheck: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    [NODES_URL]: { results: [], count: 0 },
                    ...savedQueryMocks([]),
                    [CHECKS_URL]: {
                        results: [{ ...checks[0], subject_type: 'posthog_table', subject_node_id: null }],
                        count: 1,
                    },
                },
            },
        },
    },
}

export const FirstView: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    [NODES_URL]: { results: [], count: 0 },
                    ...savedQueryMocks([]),
                    [CHECKS_URL]: { results: [], count: 0 },
                },
            },
        },
    },
}

export const FirstViewNarrow: Story = {
    ...FirstView,
    decorators: [inMainContent('w-128')],
}
