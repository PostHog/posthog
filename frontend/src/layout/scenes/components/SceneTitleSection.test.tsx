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

    // The reported Arc behaviour: the view mode title is a <button> that opened the editor on
    // `click`, which only fires on release. A press-and-drag never reached it, and a button is
    // never a text selection anchor, so the page claimed nothing and the browser took the drag.
    test('a press on the view mode title enters edit mode and is consumed', () => {
        render(<SceneName name="Paying users" canEdit onChange={jest.fn()} />)

        const title = screen.getByRole('button')
        const press = createEvent.mouseDown(title)
        fireEvent(title, press)

        expect(press.defaultPrevented).toBe(true)
        expect(screen.getByRole('textbox')).toBeInTheDocument()
    })

    // Enter and Space produce a click with no preceding press, so the click path has to stay.
    test('keyboard activation still enters edit mode', () => {
        render(<SceneName name="Paying users" canEdit onChange={jest.fn()} />)

        fireEvent.click(screen.getByRole('button'))

        expect(screen.getByRole('textbox')).toBeInTheDocument()
    })

    // Right-click on the view mode title should not enter edit mode; it should allow
    // the context menu to show instead.
    test('right-click on the view mode title does not enter edit mode', () => {
        render(<SceneName name="Paying users" canEdit onChange={jest.fn()} />)

        const title = screen.getByRole('button')
        const press = createEvent.mouseDown(title, { button: 2 })
        fireEvent(title, press)

        // Should not prevent default on right-click
        expect(press.defaultPrevented).toBe(false)
        // Should not enter edit mode
        expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    })

    // Ctrl+click is the macOS secondary press. It reports button 0, so it needs its own
    // guard or it would enter edit mode and swallow the context menu.
    test('ctrl+click on the view mode title does not enter edit mode', () => {
        render(<SceneName name="Paying users" canEdit onChange={jest.fn()} />)

        const title = screen.getByRole('button')
        const press = createEvent.mouseDown(title, { button: 0, ctrlKey: true })
        fireEvent(title, press)

        expect(press.defaultPrevented).toBe(false)
        expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    })
})
