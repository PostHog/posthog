import type { Meta, StoryObj } from '@storybook/react'

import { CheckRunsTable } from './CheckRunsTable'
import type { DataQualityCheckRunApi } from './generated/api.schemas'

const BASE_RUN: DataQualityCheckRunApi = {
    id: 'run',
    quality_check: 'check',
    check_name: null,
    suite_run: 'suite-1',
    subject_type: 'table',
    subject_uuid: '018f2a1c-0000-7000-8000-000000000001',
    subject_name: 'orders',
    check_type: 'not_null',
    column_name: '',
    check_config: null,
    check_severity: 'error',
    status: 'passed',
    failed_row_count: 0,
    observed_value: 0,
    compiled_query: 'SELECT count() FROM orders',
    error: '',
    duration_ms: 1200,
    started_at: '2026-09-04T09:00:00Z',
    finished_at: '2026-09-04T09:00:01Z',
    created_at: '2026-09-04T09:00:01Z',
}

function run(overrides: Partial<DataQualityCheckRunApi>): DataQualityCheckRunApi {
    return { ...BASE_RUN, ...overrides, id: `${overrides.check_type}-${overrides.status ?? 'passed'}` }
}

const RUNS_OF_EVERY_TYPE: DataQualityCheckRunApi[] = [
    run({
        check_type: 'freshness',
        column_name: 'updated_at',
        check_config: { max_age_minutes: 2160 },
        status: 'failed',
        failed_row_count: 1,
        observed_value: 147117,
    }),
    run({
        check_type: 'row_count',
        check_config: { min: 1000000, max: 2000000 },
        status: 'failed',
        failed_row_count: null,
        observed_value: 2493355,
    }),
    run({ check_type: 'not_null', column_name: 'email', status: 'failed', failed_row_count: 7, observed_value: 7 }),
    run({ check_type: 'unique', column_name: 'order_id', status: 'failed', failed_row_count: 1, observed_value: 1 }),
    run({
        check_type: 'accepted_values',
        column_name: 'status',
        check_config: { values: ['paid', 'refunded'] },
        status: 'failed',
        failed_row_count: 12,
        observed_value: 12,
    }),
    run({
        check_type: 'relationships',
        column_name: 'customer_id',
        status: 'failed',
        failed_row_count: 5,
        observed_value: 5,
    }),
    run({
        check_type: 'custom_sql',
        check_name: 'orders_have_a_total',
        check_config: { query: 'SELECT * FROM orders WHERE total IS NULL' },
        status: 'failed',
        failed_row_count: 9,
        observed_value: 9,
    }),
    run({ check_type: 'unique', column_name: 'order_id', status: 'passed', failed_row_count: 0, observed_value: 0 }),
    run({
        check_type: 'custom_sql',
        check_name: 'orders_have_a_total',
        status: 'errored',
        failed_row_count: null,
        observed_value: null,
        error: 'Unknown column total',
    }),
]

const meta: Meta<typeof CheckRunsTable> = {
    title: 'Data quality/Check runs table',
    component: CheckRunsTable,
    parameters: { mockDate: '2026-09-04T12:00:00Z', viewMode: 'story' },
    args: { runs: RUNS_OF_EVERY_TYPE, showCheck: true },
}
export default meta
type Story = StoryObj<typeof CheckRunsTable>

export const EveryCheckType: Story = {}
