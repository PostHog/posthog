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
        const { getByTestId } = render(<SurveyDragHandle hasMultipleQuestions={true} listeners={mockListeners} />)

        expect(getByTestId('survey-question-drag-handle')).toBeInTheDocument()
    })

    it('does not render for surveys with only one question', () => {
        const { queryByTestId } = render(<SurveyDragHandle hasMultipleQuestions={false} listeners={mockListeners} />)

        expect(queryByTestId('survey-question-drag-handle')).not.toBeInTheDocument()
    })
})
