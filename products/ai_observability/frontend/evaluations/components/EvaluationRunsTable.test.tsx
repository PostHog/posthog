import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationRun } from '../types'
import { EvaluationRunsTable } from './EvaluationRunsTable'

const props = { evaluationId: 'eval-123' }

function renderTable(): void {
    render(
        <Provider>
            <BindLogic logic={llmEvaluationLogic} props={props}>
                <EvaluationRunsTable />
            </BindLogic>
        </Provider>
    )
}

const passingRun: EvaluationRun = {
    id: 'run-1',
    evaluation_id: 'eval-123',
    evaluation_name: 'Test Evaluation',
    generation_id: 'gen-1',
    trace_id: 'trace-1',
    timestamp: '2024-01-01T10:00:00Z',
    result: true,
    reasoning: 'Good',
    status: 'completed',
}

describe('EvaluationRunsTable', () => {
    let logic: ReturnType<typeof llmEvaluationLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/projects/:teamId/evaluations/:id/': {},
            },
        })
        initKeaTests()
        logic = llmEvaluationLogic(props)
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    it('shows a retry action instead of the empty state when the query failed', () => {
        logic.actions.loadEvaluationRunsFailure('boom')
        renderTable()

        expect(screen.getByText('Could not load evaluation runs')).toBeInTheDocument()
        expect(screen.getByText('Retry')).toBeInTheDocument()
        expect(screen.queryByText('No evaluation runs yet')).not.toBeInTheDocument()
    })

    it('warns that rows are stale when a refresh fails with runs already on screen', () => {
        logic.actions.loadEvaluationRunsSuccess([passingRun])
        logic.actions.loadEvaluationRunsFailure('boom')
        renderTable()

        expect(
            screen.getByText("We couldn't refresh the evaluation runs. The runs below may be out of date.")
        ).toBeInTheDocument()
        expect(document.querySelector('[data-attr="llma-evaluation-runs-stale-retry"]')).toBeInTheDocument()
        expect(screen.getByText('Good')).toBeInTheDocument()
    })

    it('says a filter is hiding rows when the evaluation has runs but none match', () => {
        logic.actions.loadEvaluationRunsSuccess([passingRun])
        logic.actions.setEvaluationRunsFilter('fail', 'all')
        renderTable()

        expect(screen.getByText('No runs match this filter')).toBeInTheDocument()
        expect(screen.queryByText('No evaluation runs yet')).not.toBeInTheDocument()
    })

    it('shows the never-ran empty state when the evaluation truly has no runs', () => {
        logic.actions.loadEvaluationRunsSuccess([])
        renderTable()

        expect(screen.getByText('No evaluation runs yet')).toBeInTheDocument()
    })
})
