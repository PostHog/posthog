import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TestHogResultItemApi } from '../../generated/api.schemas'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationConfig } from '../types'
import { EvaluationCodeEditor, HogTestResultsPanel } from './EvaluationCodeEditor'

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

const trueResult: TestHogResultItemApi = {
    sample_id: 'gen-1',
    sample_type: 'generation',
    event_uuid: 'gen-1',
    trace_id: 'trace-1',
    input_preview: 'hello',
    output_preview: 'world',
    result: true,
    reasoning: '',
    error: null,
}

function renderPanel(): void {
    render(
        <Provider>
            <BindLogic logic={llmEvaluationLogic} props={props}>
                <HogTestResultsPanel />
            </BindLogic>
        </Provider>
    )
}

function renderEditor(): void {
    render(
        <Provider>
            <BindLogic logic={llmEvaluationLogic} props={props}>
                <EvaluationCodeEditor />
            </BindLogic>
        </Provider>
    )
}

describe('EvaluationCodeEditor', () => {
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

    it('labels a true result as a pass for a plain evaluation', () => {
        logic.actions.loadEvaluationSuccess(baseEvaluation)
        logic.actions.testHogOnSampleSuccess([trueResult])
        renderPanel()

        expect(screen.getByText('1 passed')).toBeInTheDocument()
        expect(screen.getByText('0 failed')).toBeInTheDocument()
        expect(screen.getByText('Pass')).toBeInTheDocument()
        expect(screen.queryByText('Fail')).not.toBeInTheDocument()
    })

    it('labels a true result as a fail for a detector, matching the polarity switch', () => {
        logic.actions.loadEvaluationSuccess({
            ...baseEvaluation,
            output_config: { allows_na: false, true_is_failure: true },
        })
        logic.actions.testHogOnSampleSuccess([trueResult])
        renderPanel()

        expect(screen.getByText('0 passed')).toBeInTheDocument()
        expect(screen.getByText('1 failed')).toBeInTheDocument()
        expect(screen.getByText('Fail')).toBeInTheDocument()
        expect(screen.queryByText('Pass')).not.toBeInTheDocument()
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
})
