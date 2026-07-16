import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { EvaluationDisplay } from './EvaluationDisplay'

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

    it('renders OTel scores and links to the target span', () => {
        render(
            <Provider>
                <EvaluationDisplay
                    eventProperties={{
                        $ai_trace_id: 'trace-1',
                        $ai_target_span_id: '0123456789abcdef',
                        $ai_evaluation_score_label: 'pass',
                        $ai_evaluation_score_value: 0.9,
                    }}
                />
            </Provider>
        )

        expect(screen.getByText('Pass · 0.9')).toBeInTheDocument()
        expect(screen.getByText('0123456789ab...')).toHaveAttribute('href', expect.stringContaining('0123456789abcdef'))
    })
})
