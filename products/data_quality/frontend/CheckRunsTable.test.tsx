import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { CheckRunsTable } from './CheckRunsTable'
import type { DataQualityCheckRunApi } from './generated/api.schemas'

const PASSING_METRIC_RUN: DataQualityCheckRunApi = {
    id: 'pass',
    quality_check: 'check-1',
    check_name: 'Signups stay positive',
    suite_run: 'suite-1',
    subject_type: 'metric',
    subject_uuid: '018f2a1c-0000-7000-8000-000000000001',
    subject_name: 'signups',
    check_type: 'custom_sql',
    column_name: '',
    check_config: null,
    check_severity: 'error',
    status: 'passed',
    failed_row_count: 0,
    observed_value: 0,
    compiled_query: 'SELECT count() FROM signups',
    error: '',
    duration_ms: 20,
    started_at: null,
    finished_at: null,
    created_at: '2026-09-01T00:00:00Z',
}

function metricRun(overrides: Partial<DataQualityCheckRunApi>): DataQualityCheckRunApi {
    return { ...PASSING_METRIC_RUN, ...overrides }
}

describe('CheckRunsTable', () => {
    afterEach(cleanup)
    it('shows metric failures and execution errors without an observed metric value', () => {
        initKeaTests()
        render(
            <CheckRunsTable
                subjectType="metric"
                runs={[
                    PASSING_METRIC_RUN,
                    metricRun({
                        id: 'fail',
                        status: 'failed',
                        failed_row_count: 7,
                        observed_value: 7,
                        duration_ms: 30,
                    }),
                    metricRun({
                        id: 'error',
                        status: 'errored',
                        failed_row_count: null,
                        observed_value: null,
                        duration_ms: 40,
                        error: 'Unknown column signups',
                    }),
                ]}
            />
        )
        expect(screen.getByText('passed')).toBeInTheDocument()
        expect(screen.getByText('failed')).toBeInTheDocument()
        expect(screen.getByText('errored')).toBeInTheDocument()
        expect(screen.getByText('7')).toBeInTheDocument()
        expect(screen.getByText('Unknown column signups')).toBeInTheDocument()
        expect(screen.queryByText('Observed value')).not.toBeInTheDocument()
    })
})
