import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { makeFeedback, makeFeedbackScore, makeFeedbackText } from '../testFixtures'
import { FeedbackStepContext } from '../types'
import { TraceFeedbackView } from './TraceFeedbackView'

const STEP_LABELS = new Map([
    ['trace-1', 'answer-billing-question'],
    ['gen-1', 'openai.chat #1'],
])

function steps(focusNodeId: string | null = null): FeedbackStepContext {
    return { traceId: 'trace-1', stepLabels: STEP_LABELS, focusNodeId }
}

describe('TraceFeedbackView', () => {
    beforeEach(() => {
        initKeaTests()
        Element.prototype.scrollIntoView = jest.fn()
    })

    afterEach(() => {
        cleanup()
    })

    it('links a score to its step by label and keeps trace-level and unknown steps on the whole trace', () => {
        const feedback = makeFeedback({
            scores: [
                makeFeedbackScore({ id: 'on-step', value: 'step-value', nodeId: 'gen-1' }),
                makeFeedbackScore({ id: 'on-trace', value: 'trace-value', nodeId: 'trace-1' }),
                makeFeedbackScore({ id: 'on-gone', value: 'gone-value', nodeId: 'gone' }),
            ],
            responses: [],
        })

        render(<TraceFeedbackView feedback={feedback} failed={false} steps={steps()} onSelectStep={() => {}} />)

        expect(screen.getByText('openai.chat #1')).toBeTruthy()
        expect(screen.getAllByText('Whole trace')).toHaveLength(2)
    })

    it('highlights the entries of the step it was opened from', () => {
        const feedback = makeFeedback({
            scores: [makeFeedbackScore({ id: 'on-step', value: 'step-value', nodeId: 'gen-1' })],
            responses: [makeFeedbackText({ text: 'Trace-level note', nodeId: 'trace-1' })],
        })

        render(
            <TraceFeedbackView feedback={feedback} failed={false} steps={steps('trace-1')} onSelectStep={() => {}} />
        )

        expect(screen.getByText('Trace-level note').closest('li')?.className).toContain('bg-accent-highlight-secondary')
        expect(screen.getByText('step-value').closest('tr')?.className).not.toContain('highlighted')
    })

    it('shows an error with a retry when the feedback read failed', () => {
        render(<TraceFeedbackView feedback={null} failed steps={steps()} onSelectStep={() => {}} onRetry={() => {}} />)

        expect(screen.getByText("Feedback couldn't load.")).toBeTruthy()
    })
})
