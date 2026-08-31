import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { llmEvaluationsLogic } from '../evaluations/llmEvaluationsLogic'
import { EvaluationConfig } from '../evaluations/types'
import { EvaluationDisplay } from './EvaluationDisplay'

const detectorEvaluation: EvaluationConfig = {
    id: 'eval-detector',
    name: 'Detects struggle',
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'hog',
    evaluation_config: { source: 'return true' },
    output_type: 'boolean',
    output_config: { true_is_failure: true },
    conditions: [{ id: 'cond-1', rollout_percentage: 100, properties: [] }],
    target: 'generation',
    target_config: {},
    model_configuration: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
}

describe('EvaluationDisplay', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders sentiment value instead of a boolean result', () => {
        render(
            <Provider>
                <EvaluationDisplay
                    eventProperties={{
                        $ai_evaluation_runtime: 'sentiment',
                        $ai_sentiment_label: 'positive',
                        $ai_sentiment_score: 0.91,
                    }}
                />
            </Provider>
        )

        expect(screen.getByText('Positive')).toBeInTheDocument()
        expect(screen.queryByText('False')).not.toBeInTheDocument()
    })

    it('does not coerce absent boolean results to false', () => {
        render(
            <Provider>
                <EvaluationDisplay eventProperties={{}} />
            </Provider>
        )

        expect(screen.getByText('N/A')).toBeInTheDocument()
        expect(screen.queryByText('False')).not.toBeInTheDocument()
    })

    it('colors a detector true result as danger, matching the badges elsewhere on the page', () => {
        const evaluationsLogic = llmEvaluationsLogic()
        evaluationsLogic.mount()
        evaluationsLogic.actions.loadEvaluationsSuccess([detectorEvaluation])

        render(
            <Provider>
                <EvaluationDisplay
                    eventProperties={{ $ai_evaluation_id: 'eval-detector', $ai_evaluation_result: true }}
                />
            </Provider>
        )

        expect(screen.getByText('True')).toBeInTheDocument()
        expect(document.querySelector('.LemonTag--danger')).toBeInTheDocument()
        expect(document.querySelector('.LemonTag--success')).not.toBeInTheDocument()

        evaluationsLogic.unmount()
    })
})
