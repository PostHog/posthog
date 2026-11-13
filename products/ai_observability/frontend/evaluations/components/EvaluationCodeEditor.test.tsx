import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationConfig } from '../types'
import { EvaluationCodeEditor } from './EvaluationCodeEditor'

jest.mock('lib/monaco/CodeEditorResizable', () => ({
    CodeEditorResizeable: () => <div data-attr="mock-code-editor" />,
}))

const props = { evaluationId: 'eval-123' }

const baseEvaluation: EvaluationConfig = {
    id: 'eval-123',
    name: 'Test Evaluation',
    description: '',
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'hog',
    evaluation_config: { source: 'return true' },
    output_type: 'boolean',
    output_config: { allows_na: false },
    conditions: [{ id: 'cond-1', rollout_percentage: 100, properties: [] }],
    target: 'generation',
    target_config: {},
    model_configuration: null,
    total_runs: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
}

function renderEditor(): void {
    render(
        <Provider>
            <BindLogic logic={llmEvaluationLogic} props={props}>
                <EvaluationCodeEditor />
            </BindLogic>
        </Provider>
    )
    // The authoring tips sit in a fold that starts closed.
    fireEvent.click(screen.getByText('Hog reference'))
}

describe('EvaluationCodeEditor', () => {
    let logic: ReturnType<typeof llmEvaluationLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/llm_proxy/models/': [],
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

    it('describes detector polarity in the authoring tip', () => {
        logic.actions.loadEvaluationSuccess({
            ...baseEvaluation,
            output_config: { allows_na: false, true_is_failure: true },
        })
        renderEditor()

        expect(
            screen.getByText(
                (_, element) =>
                    element?.tagName === 'LI' && element.textContent === 'Return true (fail) or false (pass)'
            )
        ).toBeInTheDocument()
    })

    it.each([
        ['Latency', 'return target.total_latency_seconds;'],
        ['Cost', 'return target.total_cost_usd;'],
    ])('enables N/A for the numeric %s example', (label, source) => {
        // Traces have no numeric templates, so the menu lists these starters.
        logic.actions.loadEvaluationSuccess({ ...baseEvaluation, output_type: 'numeric', target: 'trace' })
        renderEditor()

        fireEvent.click(screen.getByText('Insert an example'))
        fireEvent.click(screen.getByText(label))

        expect(logic.values.evaluation?.evaluation_config).toEqual({ source })
        expect(logic.values.evaluation?.output_config.allows_na).toBe(true)
        expect(screen.getByText('Number or null')).toBeInTheDocument()
    })
})
