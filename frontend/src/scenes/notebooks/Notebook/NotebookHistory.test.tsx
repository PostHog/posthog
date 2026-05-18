import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { JSONContent } from '@tiptap/core'

import { NotebookHistoryWarning } from './NotebookHistory'

// We mock kea's `useValues` / `useActions` so we can drive `NotebookHistoryWarning`
// without bootstrapping the full notebookLogic (which depends on a Tiptap editor,
// notebookCollabLogic, kea-loaders, etc.). The fix under test is purely about the
// arguments the component passes to `setLocalContent` — kea wiring is incidental.
const setLocalContent = jest.fn()
const clearPreviewContent = jest.fn()
const duplicateNotebook = jest.fn()
const setShowHistory = jest.fn()
let mockPreviewContent: JSONContent | null = null

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: () => ({ previewContent: mockPreviewContent }),
    useActions: () => ({ setLocalContent, clearPreviewContent, duplicateNotebook, setShowHistory }),
}))

jest.mock('./notebookLogic', () => ({
    notebookLogic: {},
}))

describe('NotebookHistoryWarning', () => {
    afterEach(() => {
        cleanup()
        setLocalContent.mockReset()
        clearPreviewContent.mockReset()
        duplicateNotebook.mockReset()
        setShowHistory.mockReset()
        mockPreviewContent = null
    })

    it('on Revert: clears preview and pushes the historical content into the editor', () => {
        // Regression test for the silent-no-op revert in collab mode.
        //
        // Before the fix, onRevert called `setLocalContent(previewContent)` with the
        // default `updateEditor=false`, leaving the live Tiptap editor at the
        // pre-revert state. The collab save reads `sendableSteps` from the editor and
        // `editor.getJSON()` for the wire payload, so the save sent no meaningful
        // steps and the server content was unchanged.
        //
        // The fix passes `updateEditor=true`, which makes the listener call
        // `editor.setContent(historical)` so PM-collab produces real steps for the
        // delta. We assert on the literal `true` because that single boolean is the
        // entire fix.
        const historical: JSONContent = {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'historical' }] }],
        }
        mockPreviewContent = historical

        render(<NotebookHistoryWarning />)
        fireEvent.click(screen.getByText('Revert to this version'))

        expect(clearPreviewContent).toHaveBeenCalledTimes(1)
        expect(setLocalContent).toHaveBeenCalledTimes(1)
        expect(setLocalContent).toHaveBeenCalledWith(historical, true)
        expect(setShowHistory).toHaveBeenCalledWith(false)
    })
})
