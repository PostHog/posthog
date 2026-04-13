import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { MultiQuestionForm } from '~/queries/schema/schema-assistant-messages'

import { MultiQuestionFormRecap } from './MultiQuestionForm'

describe('MultiQuestionFormRecap', () => {
    const form: MultiQuestionForm = {
        questions: [
            {
                id: 'goal',
                title: 'Goal',
                question: 'Which goal matters most?',
                type: 'select',
                options: [{ value: 'Activation' }, { value: 'Revenue' }],
            },
        ],
    }

    it('shows skipped when a submitted question has no saved answer', () => {
        render(<MultiQuestionFormRecap form={form} savedAnswers={{}} formStatus="form" />)

        expect(screen.getByText('Form submitted')).toBeInTheDocument()
        expect(screen.getByText('Skipped')).toBeInTheDocument()
    })

    it('shows a dismissed state when the form was dismissed', () => {
        render(<MultiQuestionFormRecap form={form} formStatus="dismiss_form" />)

        expect(screen.getByText('Form dismissed')).toBeInTheDocument()
        expect(screen.getByText('The user chose not to answer these questions.')).toBeInTheDocument()
    })
})
