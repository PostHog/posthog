import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { EvaluationRun } from '../evaluations/types'
import { EvaluationRunName } from './GenerationEvalRunsTable'

function makeRun(overrides: Partial<EvaluationRun> = {}): EvaluationRun {
    return {
        id: 'event-1',
        evaluation_id: 'evaluator-1',
        evaluation_name: 'Correctness',
        generation_id: 'generation-1',
        trace_id: 'trace-1',
        timestamp: '2026-04-10T12:00:00Z',
        result: true,
        reasoning: '',
        status: 'completed',
        ...overrides,
    }
}

describe('EvaluationRunName', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('links native evaluation runs to their configuration', () => {
        render(
            <Provider>
                <EvaluationRunName run={makeRun({ evaluation_type: 'hog', evaluation_source: 'online' })} />
            </Provider>
        )

        expect(screen.getByText('Correctness')).toHaveAttribute(
            'href',
            expect.stringContaining('/ai-evals/evaluations/evaluator-1')
        )
    })

    it('does not generate a configuration link for imported evaluation runs', () => {
        render(
            <Provider>
                <EvaluationRunName run={makeRun({ evaluation_type: 'otel', evaluation_source: 'imported' })} />
            </Provider>
        )

        expect(screen.getByText('Correctness')).toBeInTheDocument()
        expect(screen.queryByRole('link')).not.toBeInTheDocument()
    })
})
