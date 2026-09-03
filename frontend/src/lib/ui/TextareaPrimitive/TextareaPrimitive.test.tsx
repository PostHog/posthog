import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { TextareaPrimitive } from './TextareaPrimitive'

describe('TextareaPrimitive', () => {
    afterEach(() => {
        cleanup()
    })

    // Guards click and drag text selection: moving the caret to the end on a focus that
    // came from a pointer press collapses the selection the press started, so a drag
    // selects nothing and the gesture is left for the browser to interpret.
    it('keeps the caret where a pointer press put it', () => {
        render(<TextareaPrimitive defaultValue="a title to select" />)
        const textarea = screen.getByRole('textbox') as HTMLTextAreaElement

        fireEvent.pointerDown(textarea)
        fireEvent.focus(textarea)

        expect(textarea.selectionStart).toBe(0)
    })

    it('moves the caret to the end when focus arrives without a pointer press', () => {
        render(<TextareaPrimitive defaultValue="a title to select" />)
        const textarea = screen.getByRole('textbox') as HTMLTextAreaElement

        fireEvent.focus(textarea)

        expect(textarea.selectionStart).toBe('a title to select'.length)
    })
})
