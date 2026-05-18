import { JSONContent } from '@tiptap/core'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { NotebookEditor, NotebookType } from '../types'
import { notebookLogic } from './notebookLogic'

// Integration test for the history revert flow at the notebookLogic boundary.
// Mounts a real notebookLogic with a cached notebook (skipping the HTTP load),
// binds a stubbed Tiptap editor surface, and exercises the action sequence that
// `NotebookHistoryWarning.onRevert` dispatches. Asserts on the actual
// behaviour — what reaches the editor and how the kea state advances —
// rather than on which props the component passed.

const SHORT_ID = 'test-notebook-revert'

const CURRENT_DOC: JSONContent = {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'current' }] }],
}
const HISTORICAL_DOC: JSONContent = {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'historical' }] }],
}

const cachedNotebook: NotebookType = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Test',
    content: CURRENT_DOC as any,
    text_content: 'current',
    version: 1,
    deleted: false,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
    is_template: false,
    user_access_level: 'editor' as any,
} as unknown as NotebookType

describe('Notebook history revert', () => {
    let logic: ReturnType<typeof notebookLogic.build>
    let editorSetContent: jest.Mock

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/@current/notebooks/': () => [200, { results: [cachedNotebook] }],
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, cachedNotebook],
                '/api/projects/@current/comments/': () => [200, { results: [] }],
                '/api/projects/@current/comments/related_objects/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.NOTEBOOKS_COLLABORATION], {
            [FEATURE_FLAGS.NOTEBOOKS_COLLABORATION]: true,
        })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook })
        logic.mount()

        // Stub the NotebookEditor surface — only the methods that get exercised
        // along the revert path. setContent is the integration point we assert on.
        editorSetContent = jest.fn()
        const editor: Partial<NotebookEditor> = {
            setContent: editorSetContent,
            getJSON: () => CURRENT_DOC,
            getText: () => 'current',
            getCurrentPosition: () => 0,
            setTextSelection: jest.fn(),
            nextNode: () => null,
            insertContentAfterNode: jest.fn(),
            findCommentPosition: () => null,
            getAllCommentTexts: () => ({}),
            removeComment: jest.fn(),
        }
        logic.actions.setEditor(editor as NotebookEditor)
    })

    afterEach(() => {
        logic.unmount()
    })

    it('on Revert: clears preview and pushes the historical content into the editor', async () => {
        // User clicks a history entry — preview is set, editor visually transitions to historical
        logic.actions.setPreviewContent(HISTORICAL_DOC)
        await expectLogic(logic).toFinishAllListeners()
        expect(editorSetContent).toHaveBeenLastCalledWith(HISTORICAL_DOC)
        expect(logic.values.previewContent).toEqual(HISTORICAL_DOC)

        // User clicks "Revert to this version" — same action sequence as NotebookHistoryWarning.onRevert
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
