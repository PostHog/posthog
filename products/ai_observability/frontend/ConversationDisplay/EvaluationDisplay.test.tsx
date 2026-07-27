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
})
