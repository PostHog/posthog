import { JSONContent } from '@tiptap/core'
import * as PMCollab from '@tiptap/pm/collab'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookEditor, NotebookType } from '../types'
import { notebookCollabLogic } from './notebookCollabLogic'
import { SYNC_DELAY, notebookLogic } from './notebookLogic'

// Skip the API-driven query upgrade step inside migrate so the loader doesn't try
// to upgrade insight nodes. Our fixture content has no insight nodes anyway, but
// migrate's per-node walk + transitive imports are out of scope for this test.
jest.mock('./migrations/migrate', () => {
    const actual = jest.requireActual('./migrations/migrate')
    return {
        ...actual,
        migrate: jest.fn(async (notebook) => notebook),
    }
})

// In tests we don't run a real Tiptap editor with a collab plugin, so sendableSteps
// can't compute pending steps from a real EditorState. The collab branch of
// saveNotebook gates on a non-null sendable — return a real-looking step so the
// branch fires and we can assert on the resulting api.create call shape.
jest.mock('@tiptap/pm/collab', () => ({
    ...jest.requireActual('@tiptap/pm/collab'),
    sendableSteps: jest.fn(),
}))

const SHORT_ID = 'test-revert'

const SAMPLE_DOC: JSONContent = {
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
    content: SAMPLE_DOC,
    text_content: 'current',
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
} as unknown as NotebookType

describe('Notebook history revert flow', () => {
    let logic: ReturnType<typeof notebookLogic.build>
    let editorSetContent: jest.Mock
    let editorContent: JSONContent | null
    let apiCreateSpy: jest.SpyInstance
    let apiUpdateSpy: jest.SpyInstance

    // The stub tracks its own content so getJSON() reflects the result of setContent
    // calls. Otherwise the collab path's wire payload (which is editor.getJSON()) would
    // appear correct even when the editor never actually transitioned to the historical doc.
    const stubEditor = (): NotebookEditor =>
        ({
            setContent: (content: JSONContent) => {
                editorContent = content
                editorSetContent(content)
            },
            getJSON: () => editorContent,
            getText: () => 'historical',
            getCurrentPosition: () => 0,
            setTextSelection: jest.fn(),
        }) as unknown as NotebookEditor

    beforeEach(() => {
        editorContent = null
        useMocks({
            get: {
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, cachedNotebook],
            },
        })
        initKeaTests()

        editorSetContent = jest.fn()
        apiCreateSpy = jest.spyOn(api, 'create').mockResolvedValue({ ...cachedNotebook, version: 2 })
        apiUpdateSpy = jest
            .spyOn(api.notebooks, 'update')
            .mockResolvedValue({ ...cachedNotebook, version: 2, content: HISTORICAL_DOC })
        // collabStream opens an SSE connection that never resolves in production —
        // resolve immediately in tests so the listener doesn't dangle.
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
        ;(PMCollab.sendableSteps as jest.Mock).mockReset()
    })

    it('opening preview: setPreviewContent updates editor + reducer, no save dispatched', async () => {
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.setEditor(stubEditor())

        // user clicks a history entry
        logic.actions.setPreviewContent(HISTORICAL_DOC)
        // wait past debounce so any save would have fired
        await expectLogic(logic)
            .delay(SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(editorSetContent).toHaveBeenCalledWith(HISTORICAL_DOC)
        expect(logic.values.previewContent).toEqual(HISTORICAL_DOC)
        expect(logic.values.localContent).toBeNull()
        // previewing is non-mutating
        expect(apiCreateSpy).not.toHaveBeenCalledWith(
            expect.stringContaining(`/notebooks/${SHORT_ID}/collab/save/`),
            expect.anything()
        )
        expect(apiUpdateSpy).not.toHaveBeenCalled()
    })

    describe.each([
        {
            name: 'non-collab mode dispatches PATCH save with historical content',
            collab: false,
            expectedSave: 'patch' as const,
        },
        {
            name: 'collab mode dispatches collab/save POST with historical content',
            collab: true,
            expectedSave: 'collab' as const,
        },
    ])('reverting to a historical version in $name', ({ collab, expectedSave }) => {
        it('clears preview, updates editor, and dispatches the right save', async () => {
            if (collab) {
                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.NOTEBOOKS_COLLABORATION], {
                    [FEATURE_FLAGS.NOTEBOOKS_COLLABORATION]: true,
                })
                // pretend the editor has a pending step ready to send
                ;(PMCollab.sendableSteps as jest.Mock).mockReturnValue({
                    version: 1,
                    steps: [{ toJSON: () => ({ stepType: 'replace', from: 0, to: 0, slice: { content: [] } }) }],
                    clientID: 'test-client',
                })
            }

            // load the notebook
            logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook })
            logic.mount()
            logic.actions.setEditor(stubEditor())
            if (collab) {
                notebookCollabLogic({ shortId: SHORT_ID }).actions.bindEditor({
                    state: { selection: { head: 0 } },
                } as any)
            }
            logic.actions.loadNotebook()
            await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

            // user clicks a history entry
            logic.actions.setPreviewContent(HISTORICAL_DOC)
            editorSetContent.mockClear()

            // user clicks Revert — mirror the full action sequence in NotebookHistoryWarning.onRevert.
            // setShowHistory(false)'s listener fires a second clearPreviewContent, so leaving it out
            // would skip part of the sequence that runs in production.
            logic.actions.clearPreviewContent()
            logic.actions.setLocalContent(HISTORICAL_DOC, true)
            logic.actions.setShowHistory(false)
            // wait past debounce
            await expectLogic(logic)
                .delay(SYNC_DELAY + 100)
                .toFinishAllListeners()

            expect(editorSetContent).toHaveBeenCalledWith(HISTORICAL_DOC)
            expect(logic.values.previewContent).toBeNull()
            // localContent is cleared by saveNotebook once the save resolves
            expect(logic.values.localContent).toBeNull()

            if (expectedSave === 'collab') {
                expect(apiCreateSpy).toHaveBeenCalledWith(
                    `api/projects/@current/notebooks/${SHORT_ID}/collab/save/`,
                    expect.objectContaining({ content: HISTORICAL_DOC, client_id: 'test-client' })
                )
                expect(apiUpdateSpy).not.toHaveBeenCalled()
            } else {
                expect(apiUpdateSpy).toHaveBeenCalledWith(
                    SHORT_ID,
                    expect.objectContaining({ content: HISTORICAL_DOC, version: 1 })
                )
                expect(apiCreateSpy).not.toHaveBeenCalledWith(
                    expect.stringContaining(`/notebooks/${SHORT_ID}/collab/save/`),
                    expect.anything()
                )
            }
        })
    })
})
