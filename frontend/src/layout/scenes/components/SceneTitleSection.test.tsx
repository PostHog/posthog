import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

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

    // Guards the other half of the cohort "name cannot be empty" desync. `renameDebounceMs={0}`
    // means no debounce, so a keystroke must reach the consumer in the same tick. A 0ms timer runs
    // after the Save click that follows it, and the form then validates an empty name.
    test('commits in the same tick when no debounce is configured', () => {
        const onChange = jest.fn()
        render(<SceneName name="" onChange={onChange} canEdit renameDebounceMs={0} />)

        fireEvent.click(screen.getByRole('button'))
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Paying users' } })

        // No timers advanced and no blur — the value is already committed
        expect(onChange).toHaveBeenCalledWith('Paying users')
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
