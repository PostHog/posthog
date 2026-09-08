import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { CheckRunsTable } from './CheckRunsTable'
import type { DataQualityCheckRunApi } from './generated/api.schemas'

describe('CheckRunsTable', () => {
    afterEach(cleanup)
    it('shows metric failures and execution errors without an observed metric value', () => {
        initKeaTests()
        render(
            <CheckRunsTable
                subjectType="metric"
                runs={
                    [
                        {
                            id: 'pass',
                            status: 'passed',
                            failed_row_count: 0,
                            duration_ms: 20,
                            observed_value: 0,
                            error: '',
                        },
                        {
                            id: 'fail',
                            status: 'failed',
                            failed_row_count: 7,
                            duration_ms: 30,
                            observed_value: 7,
                            error: '',
                        },
                        {
                            id: 'error',
                            status: 'errored',
                            failed_row_count: null,
                            duration_ms: 40,
                            observed_value: null,
                            error: 'Unknown column signups',
                        },
                    ] as DataQualityCheckRunApi[]
                }
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
