import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { SurveyDragHandle } from './SurveyDragHandle'

describe('SurveyDragHandle', () => {
    beforeEach(() => {
        cleanup()
    })

    const mockListeners = {
        onKeyDown: jest.fn(),
        onMouseDown: jest.fn(),
    }

    it('renders drag handle for draft surveys with multiple questions', () => {
        const { getByTestId } = render(
            <SurveyDragHandle
                isDraftSurvey={true}
                hasMultipleQuestions={true}
                listeners={mockListeners}
                allQuestionsHaveIds={false}
            />
        )

        expect(getByTestId('survey-question-drag-handle')).toBeInTheDocument()
    })

    it('does not render for non-draft surveys without ids', () => {
        const { queryByTestId } = render(
            <SurveyDragHandle
                isDraftSurvey={false}
                hasMultipleQuestions={true}
                listeners={mockListeners}
                allQuestionsHaveIds={false}
            />
        )

        expect(queryByTestId('survey-question-drag-handle')).not.toBeInTheDocument()
    })

    it('does render for non-draft surveys with ids', () => {
        const { queryByTestId } = render(
            <SurveyDragHandle
                isDraftSurvey={false}
                hasMultipleQuestions={true}
                listeners={mockListeners}
                allQuestionsHaveIds={true}
            />
        )

        expect(queryByTestId('survey-question-drag-handle')).toBeInTheDocument()
    })

    it('does not render for surveys with only one question', () => {
        const { queryByTestId } = render(
            <SurveyDragHandle
                isDraftSurvey={true}
                hasMultipleQuestions={false}
                listeners={mockListeners}
                allQuestionsHaveIds={false}
            />
        )

        expect(queryByTestId('survey-question-drag-handle')).not.toBeInTheDocument()
    })
})
