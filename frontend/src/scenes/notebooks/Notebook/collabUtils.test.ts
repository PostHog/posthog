import { notebookEditorLogicKey, shouldUseNotebookCollab } from './collabUtils'

describe('collabUtils', () => {
    describe('shouldUseNotebookCollab', () => {
        it.each([
            { collabEnabled: true, hasNotebook: true, hasPreviewContent: false, expected: true },
            { collabEnabled: false, hasNotebook: true, hasPreviewContent: false, expected: false },
            { collabEnabled: true, hasNotebook: false, hasPreviewContent: false, expected: false },
            { collabEnabled: true, hasNotebook: true, hasPreviewContent: true, expected: false },
        ])(
            'returns $expected for collabEnabled=$collabEnabled, hasNotebook=$hasNotebook, hasPreviewContent=$hasPreviewContent',
            ({ collabEnabled, hasNotebook, hasPreviewContent, expected }) => {
                expect(shouldUseNotebookCollab(collabEnabled, hasNotebook, hasPreviewContent)).toBe(expected)
            }
        )
    })

    describe('notebookEditorLogicKey', () => {
        it('uses a different editor key when collaboration is active', () => {
            expect(notebookEditorLogicKey('abc123', true)).toBe('Notebook.abc123-collab')
            expect(notebookEditorLogicKey('abc123', false)).toBe('Notebook.abc123')
        })
    })
})
