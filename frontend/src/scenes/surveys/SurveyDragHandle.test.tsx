import { render } from '@testing-library/react'

import { SurveyDragHandle } from './SurveyDragHandle'

describe('SurveyDragHandle', () => {
    const mockListeners = {
        onKeyDown: jest.fn(),
        onMouseDown: jest.fn(),
    }

    it('renders drag handle for draft surveys with multiple questions', () => {
        const { getByTestId } = render(
            <SurveyDragHandle isDraftSurvey={true} hasMultipleQuestions={true} listeners={mockListeners} />
        )

        expect(getByTestId('survey-question-drag-handle')).toBeInTheDocument()
    })

    it('does not render for non-draft surveys', () => {
        const { queryByTestId } = render(
            <SurveyDragHandle isDraftSurvey={false} hasMultipleQuestions={true} listeners={mockListeners} />
        )

        expect(queryByTestId('survey-question-drag-handle')).not.toBeInTheDocument()
    })

    it('does not render for surveys with only one question', () => {
        const { queryByTestId } = render(
            <SurveyDragHandle isDraftSurvey={true} hasMultipleQuestions={false} listeners={mockListeners} />
        )

        expect(queryByTestId('survey-question-drag-handle')).not.toBeInTheDocument()
    })
})
