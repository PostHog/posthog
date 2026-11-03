import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'
import { NodeKind } from '~/queries/schema/schema-general'

import { TablesTab } from './TablesTab'

const LONG_VIEW_NAME = 'monthly_revenue_summary_by_region_and_channel_v2'

function posthogTable(name: string): Record<string, unknown> {
    return { type: 'posthog', id: name, name, fields: {} }
}

function sourceTable(
    id: string,
    name: string,
    sourceType: string | null,
    lastSyncedAt: string
): Record<string, unknown> {
    return {
        type: 'data_warehouse',
        id,
        name,
        fields: {},
        format: 'Parquet',
        url_pattern: '',
        ...(sourceType
            ? {
                  source: { id: `source-${sourceType}`, source_type: sourceType, status: 'Completed', prefix: '' },
                  schema: {
                      id: `schema-${id}`,
                      name,
                      should_sync: true,
                      incremental: true,
                      last_synced_at: lastSyncedAt,
                  },
              }
            : {}),
    }
}

function view(id: string, name: string): Record<string, unknown> {
    return { type: 'view', id, name, fields: {}, query: { kind: 'HogQLQuery', query: 'select 1' } }
}

const databaseTables = Object.fromEntries(
    [
        posthogTable('events'),
        posthogTable('persons'),
        posthogTable('groups'),
        posthogTable('sessions'),
        sourceTable('table-charges', 'stripe.charges', 'Stripe', '2026-09-14T20:10:00Z'),
        sourceTable('table-customers', 'stripe.customers', 'Stripe', '2026-09-14T20:10:00Z'),
        sourceTable('table-contacts', 'hubspot.contacts', 'Hubspot', '2026-09-14T23:00:00Z'),
        sourceTable('table-s3-orders', 'orders_export', null, ''),
        view('view-orders-daily', 'orders_daily'),
        view('view-revenue-by-account', 'revenue_by_account'),
        view('view-long-name', LONG_VIEW_NAME),
    ].map((table) => [table.name as string, table])
)

function check(
    id: string,
    name: string,
    subjectType: string,
    subjectUuid: string,
    subjectName: string,
    lastStatus: string | null
): Record<string, unknown> {
    return {
        id,
        name,
        check_type: 'not_null',
        column_name: 'id',
        severity: 'error',
        enabled: true,
        subject_type: subjectType,
        subject_uuid: subjectUuid,
        subject_name: subjectName,
        subject_node_id: null,
        last_status: lastStatus,
        last_run_at: lastStatus ? '2026-09-14T18:00:00Z' : null,
    }
}

const passingChecks = [
    check('check-events', 'events arrive every hour', 'posthog_table', 'posthog-events', 'events', 'passed'),
    check('check-charges-1', 'charge id is never null', 'table', 'table-charges', 'stripe.charges', 'passed'),
    check('check-charges-2', 'customer id is never null', 'table', 'table-charges', 'stripe.charges', 'passed'),
    check('check-charges-3', 'amount is positive', 'table', 'table-charges', 'stripe.charges', 'passed'),
    check('check-orders-1', 'order id is unique', 'view', 'view-orders-daily', 'orders_daily', 'passed'),
]

const failingChecks = [
    ...passingChecks,
    check('check-orders-2', 'order total is never null', 'view', 'view-orders-daily', 'orders_daily', 'failed'),
    check('check-long-1', 'region is never null', 'view', 'view-long-name', LONG_VIEW_NAME, 'errored'),
]

function healthFor(checks: Record<string, unknown>[]): Record<string, unknown>[] {
    const bySubject = new Map<string, Record<string, unknown>[]>()
    for (const entry of checks) {
        const key = `${entry.subject_type}:${entry.subject_uuid}`
        bySubject.set(key, [...(bySubject.get(key) ?? []), entry])
    }
    return [...bySubject.values()].map((subjectChecks) => {
        const failing = subjectChecks.filter((entry) => entry.last_status !== 'passed').length
        return {
            subject_type: subjectChecks[0].subject_type,
            subject_uuid: subjectChecks[0].subject_uuid,
            health: failing > 0 ? 'failing' : 'healthy',
            checks_total: subjectChecks.length,
            checks_failing: failing,
        }
    })
}

function certification(
    id: string,
    target: { table?: string; saved_query?: string },
    targetName: string,
    status: string,
    proposedStatus: string = status
): Record<string, unknown> {
    return {
        id,
        table: target.table ?? null,
        saved_query: target.saved_query ?? null,
        target_type: target.table ? 'table' : 'view',
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
    certification('cert-orders', { saved_query: 'view-orders-daily' }, 'orders_daily', 'proposed', 'certified'),
    certification('cert-customers', { table: 'table-customers' }, 'stripe.customers', 'certified'),
    certification('cert-contacts', { table: 'table-contacts' }, 'hubspot.contacts', 'deprecated'),
    certification(
        'cert-revenue',
        { saved_query: 'view-revenue-by-account' },
        'revenue_by_account',
        'proposed',
        'deprecated'
    ),
]

const nodes = [
    {
        id: 'node-orders-daily',
        name: 'orders_daily',
        type: 'matview',
        saved_query_id: 'view-orders-daily',
        last_run_at: '2026-09-14T22:00:00Z',
        created_at: '2026-09-01T00:00:00Z',
        updated_at: '2026-09-01T00:00:00Z',
        upstream_count: 1,
        downstream_count: 0,
    },
]

function mocks(checks: Record<string, unknown>[]): Mocks {
    return {
        get: {
            '/api/projects/:team_id/data_quality_checks/': { results: checks, count: checks.length },
            '/api/projects/:team_id/data_quality_checks/health/': healthFor(checks),
            '/api/projects/:team_id/data_quality_checks/schedules/': [],
            '/api/projects/:team_id/data_quality_checks/subjects/': [
                { subject_type: 'posthog_table', id: 'posthog-events', name: 'events', display_name: '' },
                { subject_type: 'posthog_table', id: 'posthog-persons', name: 'persons', display_name: '' },
                { subject_type: 'posthog_table', id: 'posthog-groups', name: 'groups', display_name: '' },
            ],
            '/api/projects/:team_id/data_catalog/certifications/': {
                results: certifications,
                count: certifications.length,
            },
            '/api/environments/:team_id/data_modeling_nodes/': { results: nodes, count: nodes.length },
            '/api/environments/:team_id/data_modeling_edges/': { results: [], count: 0 },
        },
        post: {
            '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                const { query } = (await request.json()) as { query: { kind: string } }
                if (query.kind === NodeKind.DatabaseSchemaQuery) {
                    return [200, { tables: databaseTables, joins: [] }]
                }
                return [200, {}]
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

const meta: Meta<typeof TablesTab> = {
    title: 'Products/Data catalog/Tables',
    component: TablesTab,
    decorators: [mswDecorator({}), inMainContent('w-256')],
    parameters: {
        pageUrl: urls.dataCatalog(),
        mockDate: '2026-09-15',
        featureFlags: [FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
        msw: { mocks: mocks(failingChecks) },
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof TablesTab>

export const FailingChecks: Story = {}

export const AllPassing: Story = {
    parameters: { msw: { mocks: mocks(passingChecks) } },
}

async function expandFirstRow(canvasElement: HTMLElement): Promise<void> {
    const toggle = await waitFor(() => {
        const button = canvasElement.querySelector<HTMLButtonElement>('.LemonTable__toggle button')
        if (!button) {
            throw new Error('No expandable row yet')
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

export const RowExpanded: Story = {
    play: async ({ canvasElement }) => expandFirstRow(canvasElement),
}

export const Narrow: Story = {
    decorators: [inMainContent('w-128')],
}

export const NarrowRowExpanded: Story = {
    decorators: [inMainContent('w-128')],
    play: RowExpanded.play,
}
