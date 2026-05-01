import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions } from 'kea'

import type { MultiQuestionForm } from '~/queries/schema/schema-assistant-messages'

import { MultiQuestionFormInput } from './InputFormArea'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
}))

jest.mock('use-resize-observer', () => () => ({
    height: 160,
    ref: { current: null },
}))

jest.mock('../maxThreadLogic', () => ({
    maxThreadLogic: { __mock: 'maxThreadLogic' },
}))

describe('MultiQuestionFormInput', () => {
    afterEach(() => {
        cleanup()
    })

    const continueAfterForm = jest.fn()
    const continueAfterFormDismissal = jest.fn()

    const form: MultiQuestionForm = {
        questions: [
            {
                id: 'goal',
                title: 'Goal',
                question: 'Which goal matters most?',
                type: 'select',
                options: [{ value: 'Activation' }, { value: 'Revenue' }],
            },
            {
                id: 'scope',
                title: 'Scope',
                question: 'Which area should I focus on?',
                type: 'select',
                options: [{ value: 'Checkout' }, { value: 'Onboarding' }],
            },
        ],
    }

    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({
            continueAfterForm,
            continueAfterFormDismissal,
        })
    })

    it('submits partial answers when the user skips the final question', () => {
        render(<MultiQuestionFormInput form={form} />)

        fireEvent.click(screen.getByText('Activation'))
        expect(screen.getByText('Which area should I focus on?')).toBeInTheDocument()

        fireEvent.click(screen.getAllByRole('button', { name: 'Skip question' }).at(-1)!)

        expect(continueAfterForm).toHaveBeenCalledWith({ goal: 'Activation' })
    })

    it('deselecting an option clears the answer and stays on the same question', () => {
        render(<MultiQuestionFormInput form={form} initialAnswers={{ goal: 'Activation' }} />)

        // Navigate to the first question (it should already be showing since second is incomplete)
        // With initialAnswers, question 1 is complete so the form starts on question 2.
        // Click the "Goal" tab to go back.
        fireEvent.click(screen.getByText('Goal'))

        // Click the already-selected option to deselect
        fireEvent.click(screen.getByText('Activation'))

        // Should stay on the same question (not advance) and not submit the form
        expect(screen.getByText('Which goal matters most?')).toBeInTheDocument()
        expect(continueAfterForm).not.toHaveBeenCalled()
    })

    it('dismisses the form when requested', () => {
        render(<MultiQuestionFormInput form={form} />)

        fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss form' }).at(-1)!)

        expect(continueAfterFormDismissal).toHaveBeenCalledTimes(1)
        expect(screen.getByText('Dismissing form...')).toBeInTheDocument()
    })

    it('submits multi_select answers including custom entries', () => {
        const multiSelectForm: MultiQuestionForm = {
            questions: [
                {
                    id: 'goal',
                    title: 'Goal',
                    question: 'Pick a goal',
                    type: 'select',
                    options: [{ value: 'Growth' }, { value: 'Retention' }],
                },
                {
                    id: 'features',
                    title: 'Features',
                    question: 'Which features do you want?',
                    type: 'multi_select',
                    options: [{ value: 'Funnels' }, { value: 'Paths' }],
                },
            ],
        }

        render(<MultiQuestionFormInput form={multiSelectForm} />)

        // Answer first question to advance
        fireEvent.click(screen.getByText('Growth'))

        // Now on multi_select question: check a predefined option
        fireEvent.click(screen.getByText('Funnels'))

        // Add a custom entry
        const input = screen.getByPlaceholderText('Add your own option...')
        fireEvent.change(input, { target: { value: 'Custom insight' } })
        fireEvent.click(screen.getByRole('button', { name: /Add/ }))

        // Click Next to submit the multi_select answer (button says "Next" because
        // the parent answers state hasn't been updated with this question's value yet)
        const nextButton = screen.getAllByRole('button').find((b) => b.textContent === 'Next')
        fireEvent.click(nextButton!)

        expect(continueAfterForm).toHaveBeenCalledWith({
            goal: 'Growth',
            features: ['Funnels', 'Custom insight'],
        })
    })
})
