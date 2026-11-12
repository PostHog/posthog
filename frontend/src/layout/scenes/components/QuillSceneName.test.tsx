import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { TooltipProvider } from '@posthog/quill'

import { QuillSceneName } from './QuillSceneName'

describe('QuillSceneName', () => {
    afterEach(() => {
        cleanup()
    })

    const tooltip = (): Element | null => document.querySelector('[data-slot="tooltip-content"]')

    const renderName = (error: string | undefined, forceEdit = true): JSX.Element => (
        <TooltipProvider>
            <QuillSceneName name="" onChange={jest.fn()} canEdit forceEdit={forceEdit} error={error} />
        </TooltipProvider>
    )

    test('marks an empty required name invalid, explains why on focus, and keeps focus once the error clears', async () => {
        const { rerender } = render(renderName('Cohort name cannot be empty'))
        const input = screen.getByLabelText('Name')

        expect(input).toHaveAttribute('aria-invalid', 'true')
        expect(input).toHaveAccessibleDescription('Cohort name cannot be empty')
        input.focus()
        await waitFor(() => expect(tooltip()).toHaveTextContent('Cohort name cannot be empty'))

        fireEvent.keyDown(input, { key: 'Escape' })
        await waitFor(() => expect(tooltip()).not.toBeInTheDocument())

        rerender(renderName(undefined))
        expect(screen.getByLabelText('Name')).toBe(input)
        expect(input).toHaveFocus()
        expect(input).not.toHaveAttribute('aria-invalid')
    })

    test('opens a closed name field when it has an error, so the error shows on the field', () => {
        const { rerender } = render(renderName(undefined, false))
        expect(screen.queryByLabelText('Name')).not.toBeInTheDocument()

        rerender(renderName('Cohort name cannot be empty', false))
        expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true')
    })
})
