import '@testing-library/jest-dom'

import { cleanup, createEvent, fireEvent, render, screen } from '@testing-library/react'

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

    // Guards the reconciliation change: a genuine external update (loading a resource,
    // an AI-generated name) must still replace the field's value.
    test('adopts an external name change into the field', () => {
        const { rerender } = render(<SceneName name="Old name" canEdit onChange={jest.fn()} />)
        expect(screen.getByText('Old name')).toBeInTheDocument()

        rerender(<SceneName name="Generated name" canEdit onChange={jest.fn()} />)
        expect(screen.getByText('Generated name')).toBeInTheDocument()
    })

    // Guards click and drag text selection: the edit row is wider and taller than the field
    // inside it, so a press that misses the glyphs by a few pixels lands on the row. Left
    // unclaimed, some browsers read that press as their own gesture rather than a selection.
    test('a press on the edit row beside the field focuses the field and is consumed', () => {
        render(<SceneName name="Paying users" canEdit forceEdit onChange={jest.fn()} />)

        const row = screen.getByTestId('scene-name-edit-row')
        const textarea = screen.getByRole('textbox')
        expect(textarea).not.toHaveFocus()

        const press = createEvent.mouseDown(row)
        fireEvent(row, press)

        expect(textarea).toHaveFocus()
        expect(press.defaultPrevented).toBe(true)
    })

    // The counterpart: a press on the field itself must reach the browser untouched,
    // or it would never start a selection.
    test('a press on the field itself is left alone', () => {
        render(<SceneName name="Paying users" canEdit forceEdit onChange={jest.fn()} />)

        const press = createEvent.mouseDown(screen.getByRole('textbox'))
        fireEvent(screen.getByRole('textbox'), press)

        expect(press.defaultPrevented).toBe(false)
    })
})
