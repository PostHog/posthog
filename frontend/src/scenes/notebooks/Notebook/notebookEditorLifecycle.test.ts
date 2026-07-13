import { initKeaTests } from '~/test/init'

import { NotebookEditor } from '../types'
import { notebookLogic } from './notebookLogic'

describe('notebook editor lifecycle', () => {
    let logic: ReturnType<typeof notebookLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = notebookLogic({ shortId: 'canvas-person-id', mode: 'canvas' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('releases only the editor instance that was destroyed', () => {
        const firstEditor = {} as NotebookEditor
        const replacementEditor = {} as NotebookEditor

        logic.actions.setEditor(firstEditor)
        logic.actions.setEditor(replacementEditor)
        logic.actions.releaseEditor(firstEditor)

        expect(logic.values.editor).toBe(replacementEditor)

        logic.actions.releaseEditor(replacementEditor)

        expect(logic.values.editor).toBeNull()
    })
})
