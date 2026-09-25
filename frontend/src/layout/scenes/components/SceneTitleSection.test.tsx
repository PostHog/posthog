import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { SceneName } from './SceneTitleSection'

describe('SceneName', () => {
    afterEach(() => {
        cleanup()
    })

    // Guards the cohort "name cannot be empty" desync: the field debounces its
    // onChange, but a Save click blurs the field first — the pending value must be
    // committed synchronously on blur so the following submit validates what the user typed.
    test('flushes the pending debounced change on blur so onChange fires before a submit', () => {
        const onChange = jest.fn()
        render(<SceneName name="" onChange={onChange} canEdit renameDebounceMs={1000} />)

        // Enter edit mode (non-forceEdit fields start as a button)
        fireEvent.click(screen.getByRole('button'))

        const textarea = screen.getByRole('textbox')
        fireEvent.change(textarea, { target: { value: 'Paying users' } })
        // Debounce timer has NOT fired yet, so without the flush onChange would be empty here
        expect(onChange).not.toHaveBeenCalled()

        fireEvent.blur(textarea)
        expect(onChange).toHaveBeenCalledWith('Paying users')
    })

    // Guards a duplicate rename request: Enter saves the value straight away, and the name prop
    // only catches up once that save round-trips, so the blur right after it used to save again.
    // The second half guards the over-correction — a rejected save must stay retryable, so the
    // field may not treat the value as saved for good.
    test('saves an Enter-then-blur rename once, and still saves it again on a later blur', () => {
        jest.useFakeTimers()
        try {
            const onChange = jest.fn()
            render(<SceneName name="Old name" onChange={onChange} canEdit saveOnBlur renameDebounceMs={0} />)

            fireEvent.click(screen.getByRole('button'))

            const textarea = screen.getByRole('textbox')
            fireEvent.change(textarea, { target: { value: 'New name' } })
            fireEvent.keyDown(textarea, { key: 'Enter' })
            fireEvent.blur(textarea)
            act(() => {
                jest.advanceTimersByTime(1)
            })

            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange).toHaveBeenCalledWith('New name')

            // The save was rejected, so the name prop still holds the old title.
            fireEvent.click(screen.getByRole('button'))
            fireEvent.blur(screen.getByRole('textbox'))
            act(() => {
                jest.advanceTimersByTime(1)
            })

            expect(onChange).toHaveBeenCalledTimes(2)
        } finally {
            jest.useRealTimers()
        }
    })

    // Guards the reconciliation change: a genuine external update (loading a resource,
    // an AI-generated name) must still replace the field's value.
    test('adopts an external name change into the field', () => {
        const { rerender } = render(<SceneName name="Old name" canEdit onChange={jest.fn()} />)
        expect(screen.getByText('Old name')).toBeInTheDocument()

        rerender(<SceneName name="Generated name" canEdit onChange={jest.fn()} />)
        expect(screen.getByText('Generated name')).toBeInTheDocument()
    })
})
