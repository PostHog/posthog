import type { editor } from 'monaco-editor'

import { isEditorAlive } from './sqlEditorLogic'

// After Monaco disposes an editor (e.g. the SQL/BI view toggle tears it down), it drops both its
// model and its DOM node. Decoration and overlay writes that follow crash the render loop and blank
// the results pane until reload, so every write is gated on this liveness check.
function makeEditor(model: unknown, domNode: unknown): editor.IStandaloneCodeEditor {
    return {
        getModel: () => model,
        getDomNode: () => domNode,
    } as unknown as editor.IStandaloneCodeEditor
}

describe('isEditorAlive', () => {
    it('is true only when both the model and DOM node are present', () => {
        expect(isEditorAlive(makeEditor({}, document.createElement('div')))).toBe(true)
    })

    it('is false for a disposed editor that dropped its model', () => {
        expect(isEditorAlive(makeEditor(null, document.createElement('div')))).toBe(false)
    })

    it('is false for a disposed editor that dropped its DOM node', () => {
        expect(isEditorAlive(makeEditor({}, null))).toBe(false)
    })

    it('is false for a missing editor', () => {
        expect(isEditorAlive(null)).toBe(false)
        expect(isEditorAlive(undefined)).toBe(false)
    })
})
