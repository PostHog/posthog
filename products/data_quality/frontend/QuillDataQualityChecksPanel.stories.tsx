import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'
import type { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { QuillDataQualityChecksPanel, QuillDataQualityChecksPanelProps } from './QuillDataQualityChecksPanel'

const SUBJECT_ID = 'view-orders'

const columns = ['order_id', 'customer_id', 'status', 'created_at'].map(
    (name) => ({ name, type: 'string', hogql_value: name, schema_valid: true }) as DatabaseSchemaField
)

function check(id: string, overrides: Record<string, unknown>): Record<string, unknown> {
    return {
        id,
        name: '',
        description: '',
        check_type: 'not_null',
        column_name: 'order_id',
        severity: 'error',
        enabled: true,
        tags: [],
        config: {},
        subject_type: 'view',
        subject_uuid: SUBJECT_ID,
        subject_name: 'orders_daily',
        last_status: 'passed',
        last_run_at: '2026-09-14T18:00:00Z',
        last_succeeded_at: '2026-09-14T18:00:00Z',
        failing_since: null,
        created_source: 'user',
        ...overrides,
    }
}

const checks = [
    check('check-not-null', {
        name: 'order_id_not_null',
        description: 'Every order needs an id.',
        severity: 'warn',
    }),
    check('check-unique', {
        check_type: 'unique',
        column_name: 'customer_id',
        last_status: 'failed',
        failing_since: '2026-09-13T06:00:00Z',
        last_succeeded_at: '2026-09-12T06:00:00Z',
    }),
    check('check-values', {
        check_type: 'accepted_values',
        column_name: 'status',
        severity: 'warn',
        config: { values: ['paid', 'refunded'] },
        created_source: 'ai_generated',
        confidence: 'high',
        reasoning: 'The column only ever held these two values.',
        last_status: 'errored',
        failing_since: '2026-09-14T18:00:00Z',
        last_succeeded_at: null,
    }),
    check('check-rows', {
        check_type: 'row_count',
        column_name: '',
        enabled: false,
        config: { min: 1 },
        last_status: null,
        last_run_at: null,
    }),
]

const SUITE_RUN_OUTCOMES: [string, string, number, number, number][] = [
    ['materialization', 'completed', 1, 1, 1],
    ['manual', 'empty', 0, 0, 0],
    ['scheduled', 'completed', 3, 0, 0],
    ['scheduled', 'completed', 3, 0, 0],
    ['materialization', 'completed', 2, 1, 0],
    ['scheduled', 'completed', 3, 0, 0],
    ['scheduled', 'completed', 2, 0, 1],
    ['materialization', 'completed', 3, 0, 0],
    ['scheduled', 'completed', 3, 0, 0],
    ['scheduled', 'completed', 3, 0, 0],
    ['manual', 'completed', 3, 0, 0],
    ['scheduled', 'completed', 3, 0, 0],
]

const suiteRuns = SUITE_RUN_OUTCOMES.map(([trigger, status, passed, failed, errored], index) => {
    const startedAt = new Date(Date.UTC(2026, 8, 14, 18 - index * 6, 0, 0))
    return {
        id: `suite-${index + 1}`,
        trigger,
        status,
        subject_type: 'view',
        subject_uuid: SUBJECT_ID,
        workflow_id: `wf-${index + 1}`,
        checks_passed: passed,
        checks_failed: failed,
        checks_errored: errored,
        checks_skipped: 0,
        started_at: startedAt.toISOString(),
        finished_at: new Date(startedAt.getTime() + 42_000).toISOString(),
    }
})

const checkRuns = [
    {
        id: 'run-1',
        quality_check: 'check-unique',
        check_name: '',
        suite_run: 'suite-1',
        subject_type: 'view',
        subject_uuid: SUBJECT_ID,
        subject_name: 'orders_daily',
        check_type: 'unique',
        column_name: 'customer_id',
        check_config: null,
        check_severity: 'error',
        status: 'failed',
        failed_row_count: 12,
        observed_value: 12,
        compiled_query: '',
        audited_staged_refresh: false,
        error: '',
        duration_ms: 2300,
        started_at: '2026-09-14T18:00:00Z',
        finished_at: '2026-09-14T18:00:02Z',
        created_at: '2026-09-14T18:00:00Z',
    },
]

const checkTypes = [
    { check_type: 'not_null', description: 'Fails when the column holds a null.', requires_column: true },
    { check_type: 'unique', description: 'Fails when a value appears twice.', requires_column: true },
    { check_type: 'row_count', description: 'Fails when the row count is out of range.', requires_column: false },
    { check_type: 'custom_sql', description: 'Fails when the query returns rows.', requires_column: false },
].map((type) => ({ ...type, config_schema: {} }))

function mocks({ withChecks = true }: { withChecks?: boolean } = {}): Mocks {
    const listed = withChecks ? checks : []
    return {
        get: {
            '/api/projects/:team_id/data_quality_checks/': { results: listed, count: listed.length },
            '/api/projects/:team_id/data_quality_checks/health/': withChecks
                ? [
                      {
                          subject_type: 'view',
                          subject_uuid: SUBJECT_ID,
                          health: 'failing',
                          checks_total: 3,
                          checks_failing: 2,
                      },
                  ]
                : [],
            '/api/projects/:team_id/data_quality_checks/check_types/': checkTypes,
            '/api/projects/:team_id/data_quality_checks/subjects/': [],
            '/api/projects/:team_id/data_quality_checks/output_schema/': {
                columns: [
                    { name: 'day', type: 'Nullable(Date)' },
                    { name: 'signups', type: 'UInt64' },
                ],
            },
            '/api/projects/:team_id/data_quality_checks/:id/runs/': checkRuns,
            '/api/projects/:team_id/data_quality_runs/': withChecks
                ? { results: suiteRuns, count: suiteRuns.length }
                : { results: [], count: 0 },
            '/api/projects/:team_id/data_quality_runs/:id/check_runs/': checkRuns,
        },
    }
}

const inMainContent =
    (widthClass: string): Decorator =>
    (Story) => (
        <div className={`@container/main-content ${widthClass} max-w-full p-4`}>
            <Story />
        </div>
    )

const meta: Meta<typeof QuillDataQualityChecksPanel> = {
    title: 'Products/Data quality/Quill checks panel',
    component: QuillDataQualityChecksPanel,
    args: { subjectType: 'view', subjectId: SUBJECT_ID, columns },
    decorators: [mswDecorator({}), inMainContent('w-256')],
    parameters: {
        mockDate: '2026-09-15',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
        msw: { mocks: mocks() },
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof QuillDataQualityChecksPanel>

async function click(canvasElement: HTMLElement, selector: string): Promise<void> {
    const element = await waitFor(() => {
        const found = canvasElement.ownerDocument.querySelector<HTMLElement>(selector)
        if (!found) {
            throw new Error(`${selector} not rendered yet`)
        }
        return found
    })
    element.click()
}

export const Checks: Story = {}

export const Narrow: Story = {
    decorators: [inMainContent('w-128')],
}

export const NoChecks: Story = {
    parameters: { msw: { mocks: mocks({ withChecks: false }) } },
}

export const RunsExpanded: Story = {
    play: async ({ canvasElement }) => click(canvasElement, 'button[aria-label="Show runs for Unique on customer_id"]'),
}

export const NewCheckDialog: Story = {
    play: async ({ canvasElement }) => {
        await click(canvasElement, '[data-attr="data-quality-new-check"]')
        await click(canvasElement, '[data-attr="data-quality-check-advanced-options"]')
    },
}

export const EditCheckDialog: Story = {
    play: async ({ canvasElement }) => {
        await click(canvasElement, 'button[aria-label="Actions for check order_id_not_null"]')
        const editItem = await waitFor(() => {
            const item = [...canvasElement.ownerDocument.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(
                (element) => element.textContent === 'Edit'
            )
            if (!item) {
                throw new Error('Edit item not rendered yet')
            }
            return item
        })
        editItem.click()
    },
}

const metricArgs: QuillDataQualityChecksPanelProps = {
    subjectType: 'metric',
    subjectId: 'metric-signups',
    subjectName: 'Daily signups',
    columns: [],
}

export const MetricNoChecks: Story = {
    args: metricArgs,
    parameters: { msw: { mocks: mocks({ withChecks: false }) } },
}

export const MetricNoChecksNarrow: Story = {
    args: metricArgs,
    decorators: [inMainContent('w-128')],
    parameters: { msw: { mocks: mocks({ withChecks: false }) } },
}

export const MetricStarterCheck: Story = {
    args: metricArgs,
    parameters: { msw: { mocks: mocks({ withChecks: false }) } },
    play: async ({ canvasElement }) => {
        await click(canvasElement, '[data-attr="data-quality-metric-starter-no_sharp_drop"]')
        await click(canvasElement, '[data-attr="data-quality-metric-add-starter-check"]')
    },
}

export const TableChecks: Story = {
    args: { subjectType: 'table', subjectId: 'table-stripe-charges' },
}

export const MetricChecks: Story = {
    args: { ...metricArgs, hideTitle: true },
}

export const RunHistoryDialog: Story = {
    play: async ({ canvasElement }) => click(canvasElement, '[data-attr="data-quality-view-run-history"]'),
}
