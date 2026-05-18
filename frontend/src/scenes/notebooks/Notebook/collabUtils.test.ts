import { notebookEditorLogicKey, shouldUseNotebookCollab } from './collabUtils'

describe('collabUtils', () => {
    describe('shouldUseNotebookCollab', () => {
        it('enables collaboration only for loaded live notebooks', () => {
            expect(shouldUseNotebookCollab(true, true, false)).toBe(true)
            expect(shouldUseNotebookCollab(false, true, false)).toBe(false)
            expect(shouldUseNotebookCollab(true, false, false)).toBe(false)
            expect(shouldUseNotebookCollab(true, true, true)).toBe(false)
        })
    })

    describe('notebookEditorLogicKey', () => {
        it('uses a different editor key when collaboration is active', () => {
            expect(notebookEditorLogicKey('abc123', true)).toBe('Notebook.abc123-collab')
            expect(notebookEditorLogicKey('abc123', false)).toBe('Notebook.abc123')
        })
    })
})
