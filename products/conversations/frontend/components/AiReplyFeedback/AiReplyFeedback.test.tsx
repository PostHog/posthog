import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import { AiReplyFeedback } from './AiReplyFeedback'

describe('AiReplyFeedback', () => {
    it('sends the picked reasons after a not useful rating', () => {
        const onSubmit = jest.fn()
        const { rerender } = render(<AiReplyFeedback rating={null} onSubmit={onSubmit} />)

        expect(screen.queryByText('Wrong facts')).not.toBeInTheDocument()
        fireEvent.click(screen.getByText('Not useful'))
        expect(onSubmit).toHaveBeenLastCalledWith('bad')

        rerender(<AiReplyFeedback rating="bad" onSubmit={onSubmit} />)
        fireEvent.click(screen.getByText('Wrong facts'))
        fireEvent.click(screen.getByText('Too vague'))
        fireEvent.click(screen.getByText('Too vague'))
        fireEvent.click(screen.getByText('Send'))

        expect(onSubmit).toHaveBeenLastCalledWith('bad', undefined, ['wrong_facts'])
        expect(screen.getByText('Thanks for your feedback')).toBeInTheDocument()
        expect(screen.queryByText('Wrong facts')).not.toBeInTheDocument()
    })
})
