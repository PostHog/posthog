import { JSONContent } from '@tiptap/core'
import { expectLogic } from 'kea-test-utils'

import { NotebookEditor } from '../types'
import { notebookLogic } from './notebookLogic'

import { initKeaTests } from '~/test/init'

const SHORT_ID = 'test-notebook-revert'

const HISTORICAL_DOC: JSONContent = {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'historical' }] }],
}

describe('Notebook history revert', () => {
    let logic: ReturnType<typeof notebookLogic.build>
    let editorSetContent: jest.Mock

    beforeEach(() => {
        initKeaTests()

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()

        // Stub the NotebookEditor surface — only the methods exercised along the revert path.
        // setContent is the integration point we assert on.
        editorSetContent = jest.fn()
        logic.actions.setEditor({ setContent: editorSetContent } as unknown as NotebookEditor)
    })

    afterEach(() => {
        logic.unmount()
    })

    it('on Revert: clears preview and pushes the historical content into the editor', async () => {
        // User clicks a history entry — preview is set, editor visually transitions to historical.
        logic.actions.setPreviewContent(HISTORICAL_DOC)
        await expectLogic(logic).toFinishAllListeners()
        expect(editorSetContent).toHaveBeenLastCalledWith(HISTORICAL_DOC)
        expect(logic.values.previewContent).toEqual(HISTORICAL_DOC)

        // User clicks "Revert to this version" — same action sequence as NotebookHistoryWarning.onRevert.
        editorSetContent.mockClear()
        logic.actions.clearPreviewContent()
        logic.actions.setLocalContent(HISTORICAL_DOC, true)
        await expectLogic(logic).toFinishAllListeners()

        // The fix: setLocalContent's updateEditor=true branch pushes the historical doc into the editor,
        // so prosemirror-collab generates real steps for the delta and the collab save isn't a no-op.
        expect(editorSetContent).toHaveBeenCalledWith(HISTORICAL_DOC)
        expect(logic.values.previewContent).toBeNull()
        expect(logic.values.localContent).toEqual(HISTORICAL_DOC)
    })
})
