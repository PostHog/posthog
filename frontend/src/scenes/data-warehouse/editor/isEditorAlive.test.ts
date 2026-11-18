import type { editor } from 'monaco-editor'

import { isEditorAlive } from './sqlEditorLogic'

// A disposed Monaco editor drops its DOM node. `setModel` on it throws inside Monaco's
// `_attachModel` and crashes the React commit, so every write is gated on this check.
function makeEditor(domNode: unknown): editor.IStandaloneCodeEditor {
    return {
        getDomNode: () => domNode,
    } as unknown as editor.IStandaloneCodeEditor
}

describe('isEditorAlive', () => {
    it('is true for an editor with a DOM node, even without a model', () => {
        expect(isEditorAlive(makeEditor(document.createElement('div')))).toBe(true)
    })

    it('is false for a disposed editor that dropped its DOM node', () => {
        expect(isEditorAlive(makeEditor(null))).toBe(false)
    })

    it('is false for a missing editor', () => {
        expect(isEditorAlive(null)).toBe(false)
        expect(isEditorAlive(undefined)).toBe(false)
    })
})
