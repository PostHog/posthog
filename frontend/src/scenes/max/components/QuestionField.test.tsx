import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import type { MultiQuestionFormQuestion } from '~/queries/schema/schema-assistant-messages'

import { MultiFieldQuestion, QuestionField } from './QuestionField'

describe('QuestionField', () => {
    const baseQuestion: MultiQuestionFormQuestion = {
        id: 'test',
        title: 'Test',
        question: 'Test question?',
    }

    const selectQuestion: MultiQuestionFormQuestion = {
        ...baseQuestion,
        type: 'select',
        options: [
            { value: 'Option A', description: 'First option' },
            { value: 'Option B', description: 'Second option' },
        ],
    }

    it('renders select field by default', () => {
        const onAnswer = jest.fn()
        render(<QuestionField question={selectQuestion} value={undefined} onAnswer={onAnswer} />)
        expect(screen.getByText('Option A')).toBeInTheDocument()
        expect(screen.getByText('Option B')).toBeInTheDocument()
    })

    it('renders multi_select with checkboxes', () => {
        const onAnswer = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }],
        }
        render(<QuestionField question={question} value={undefined} onAnswer={onAnswer} />)
        expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    })

    it('multi_select shows error message when submitting with no selection', () => {
        const onAnswer = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }, { value: 'Gamma' }],
        }
        render(<QuestionField question={question} value={undefined} onAnswer={onAnswer} />)

        const buttons = screen.getAllByRole('button')
        const submitButton = buttons.find((b) => b.textContent?.includes('Next'))
        expect(submitButton).toBeInTheDocument()
        fireEvent.click(submitButton!)
        expect(screen.getByText('Select at least one option')).toBeInTheDocument()
        expect(onAnswer).not.toHaveBeenCalled()
    })

    describe('MultiFieldQuestion', () => {
        const multiFieldQuestion: MultiQuestionFormQuestion = {
            id: 'config',
            title: 'Config',
            question: 'Configure your experiment',
            fields: [
                { id: 'sample', type: 'number', label: 'Sample size', min: 100, max: 10000, placeholder: 'e.g. 1000' },
                { id: 'confidence', type: 'slider', label: 'Confidence level', min: 80, max: 99 },
                { id: 'notify', type: 'toggle', label: 'Notify on complete' },
            ],
        }

        it('renders all field labels', () => {
            render(
                <MultiFieldQuestion
                    question={multiFieldQuestion}
                    answers={{ confidence: '80', notify: 'false' }}
                    onFieldChange={jest.fn()}
                    onSubmit={jest.fn()}
                />
            )
            expect(screen.getByText('Sample size')).toBeInTheDocument()
            expect(screen.getByText('Confidence level')).toBeInTheDocument()
            expect(screen.getByText('Notify on complete')).toBeInTheDocument()
        })

        it('shows validation errors when submitting with empty required fields', () => {
            const onSubmit = jest.fn()
            const { container } = render(
                <MultiFieldQuestion
                    question={multiFieldQuestion}
                    answers={{ confidence: '80', notify: 'false' }}
                    onFieldChange={jest.fn()}
                    onSubmit={onSubmit}
                />
            )
            const submitButton = container.querySelector('.LemonButton--primary')
            expect(submitButton).not.toBeNull()
            fireEvent.click(submitButton!)
            expect(container.querySelector('.text-danger')).not.toBeNull()
            expect(container.querySelector('.text-danger')?.textContent).toBe('This field is required')
            expect(onSubmit).not.toHaveBeenCalled()
        })

        it('calls onSubmit when all fields are valid and button is clicked', () => {
            const onSubmit = jest.fn()
            const { container } = render(
                <MultiFieldQuestion
                    question={multiFieldQuestion}
                    answers={{ sample: '500', confidence: '95', notify: 'true' }}
                    onFieldChange={jest.fn()}
                    onSubmit={onSubmit}
                />
            )
            const submitButton = container.querySelector('.LemonButton--primary')
            expect(submitButton).not.toBeNull()
            expect(submitButton).not.toHaveAttribute('aria-disabled', 'true')
            fireEvent.click(submitButton!)
            expect(onSubmit).toHaveBeenCalled()
        })
    })
})
