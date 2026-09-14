import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { evaluationReportLogic } from '../evaluationReportLogic'
import type { EvaluationReport } from '../types'
import { EvaluationReportsCallout } from './EvaluationReportsCallout'

const EVALUATION_ID = 'evaluation-123'

function buildReport(enabled: boolean): EvaluationReport {
    return {
        id: 'report-123',
        evaluation: EVALUATION_ID,
        frequency: 'every_n',
        rrule: '',
        starts_at: null,
        timezone_name: 'UTC',
        next_delivery_date: null,
        delivery_targets: [],
        max_sample_size: 200,
        enabled,
        deleted: false,
        last_delivered_at: null,
        report_prompt_guidance: '',
        trigger_threshold: 100,
        cooldown_minutes: 60,
        daily_run_cap: 10,
        created_by: null,
        created_at: '2026-08-14T00:00:00Z',
    }
}

describe('EvaluationReportsCallout', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it.each<[name: string, reports: EvaluationReport[], expectedVisible: boolean]>([
        ['shows when no report is configured', [], true],
        ['shows for a disabled report configuration', [buildReport(false)], true],
        ['stays hidden for an enabled report configuration', [buildReport(true)], false],
    ])('%s', async (_, reports, expectedVisible) => {
        useMocks({
            get: {
                '/api/projects/:teamId/llm_analytics/evaluation_reports/': { results: reports },
                '/api/projects/:teamId/llm_analytics/evaluation_reports/:id/runs/': { results: [] },
            },
        })
        const logic = evaluationReportLogic({ evaluationId: EVALUATION_ID })
        logic.mount()

        try {
            await expectLogic(logic).toDispatchActions(['loadReportsSuccess'])
            render(
                <Provider>
                    <EvaluationReportsCallout evaluationId={EVALUATION_ID} onReportsClick={jest.fn()} />
                </Provider>
            )

            const callout = screen.queryByText(/Evaluation reports analyze these runs/)
            if (expectedVisible) {
                expect(callout).toBeInTheDocument()
            } else {
                expect(callout).not.toBeInTheDocument()
            }
        } finally {
            logic.unmount()
        }
    })
})
