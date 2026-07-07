import { JSONContent } from '@tiptap/core'
import * as PMCollab from '@tiptap/pm/collab'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, ActivityScope } from '~/types'

import { NotebookEditor, NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
import { notebookCollabLogic } from './notebookCollabLogic'
import { MARKDOWN_SYNC_DELAY, SYNC_DELAY, notebookLogic } from './notebookLogic'

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
    let apiMarkdownSaveSpy: jest.SpyInstance
    let apiActivityListLegacySpy: jest.SpyInstance
    let historyLogic: ReturnType<typeof activityLogLogic.build> | null

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
            getMarks: () => [],
            getAllCommentTexts: () => ({}),
            getAttributes: () => ({}),
            findCommentPosition: () => null,
            removeComment: jest.fn(),
            setTextSelection: jest.fn(),
        }) as unknown as NotebookEditor

    beforeEach(() => {
        localStorage.clear()
        historyLogic = null
        editorContent = null
        useMocks({
            get: {
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, cachedNotebook],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/`]: () => [200, cachedNotebook],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/kernel/status/`]: () => [200, { backend: null }],
            },
        })
        initKeaTests()

        editorSetContent = jest.fn()
        apiCreateSpy = jest.spyOn(api, 'create').mockResolvedValue({ ...cachedNotebook, version: 2 })
        apiUpdateSpy = jest
            .spyOn(api.notebooks, 'update')
            .mockResolvedValue({ ...cachedNotebook, version: 2, content: HISTORICAL_DOC })
        apiMarkdownSaveSpy = jest
            .spyOn(api.notebooks, 'markdownSave')
            .mockResolvedValue({ ...cachedNotebook, version: 2, content: HISTORICAL_DOC })
        apiActivityListLegacySpy = jest.spyOn(api.activity, 'listLegacy').mockResolvedValue({ results: [], count: 0 })
        // collabStream opens an SSE connection that never resolves in production —
        // resolve immediately in tests so the listener doesn't dangle.
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)
    })

    afterEach(() => {
        logic?.unmount()
        historyLogic?.unmount()
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

    it('does not persist editor updates emitted while previewing a historical revision', async () => {
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.setEditor(stubEditor())

        logic.actions.setPreviewContent(HISTORICAL_DOC)
        logic.actions.onEditorUpdate()

        await expectLogic(logic)
            .delay(SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(logic.values.previewContent).toEqual(HISTORICAL_DOC)
        expect(logic.values.localContent).toBeNull()
        expect(apiUpdateSpy).not.toHaveBeenCalled()
        expect(apiCreateSpy).not.toHaveBeenCalledWith(
            expect.stringContaining(`/notebooks/${SHORT_ID}/collab/save/`),
            expect.anything()
        )
    })

    it('saves through the pending content debounce after autosave resumes', async () => {
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        logic.actions.setAutosavePaused(true)
        logic.actions.setLocalContent(HISTORICAL_DOC)
        logic.actions.setAutosavePaused(false)
        expect(apiUpdateSpy).not.toHaveBeenCalled()

        await expectLogic(logic)
            .delay(SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(apiUpdateSpy).toHaveBeenCalledTimes(1)
        expect(apiUpdateSpy).toHaveBeenCalledWith(
            SHORT_ID,
            expect.objectContaining({ content: HISTORICAL_DOC, version: 1 })
        )
    })

    it('saves legacy to markdown conversion through the versioned notebook update path', async () => {
        const convertedContent = buildMarkdownNotebookContent(`# Test

converted`)
        apiUpdateSpy.mockResolvedValueOnce({
            ...cachedNotebook,
            version: 2,
            content: convertedContent,
            text_content: '# Test\n\nconverted',
        })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        logic.actions.setLocalContent(convertedContent)

        await expectLogic(logic)
            .delay(SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(apiUpdateSpy).toHaveBeenCalledWith(
            SHORT_ID,
            expect.objectContaining({
                content: convertedContent,
                text_content: '# Test\n\nconverted',
                version: 1,
            })
        )
        expect(apiMarkdownSaveSpy).not.toHaveBeenCalled()
    })

    it('refreshes notebook activity after a save when history is open', async () => {
        historyLogic = activityLogLogic({ scope: ActivityScope.NOTEBOOK, id: SHORT_ID })
        historyLogic.mount()
        await expectLogic(historyLogic).toDispatchActions(['fetchActivitySuccess']).toFinishAllListeners()
        apiActivityListLegacySpy.mockClear()

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        logic.actions.setShowHistory(true)

        await expectLogic(logic, () => {
            logic.actions.saveNotebook({ content: HISTORICAL_DOC, title: 'Test' })
        })
            .toDispatchActions(['saveNotebookSuccess'])
            .toFinishAllListeners()
        await expectLogic(historyLogic).toFinishAllListeners()

        expect(apiActivityListLegacySpy).toHaveBeenCalledWith({ scope: [ActivityScope.NOTEBOOK], id: SHORT_ID }, 1)
    })

    it('does not enable ProseMirror collaboration for markdown v2 notebooks', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.NOTEBOOKS_COLLABORATION], {
            [FEATURE_FLAGS.NOTEBOOKS_COLLABORATION]: true,
        })
        logic = notebookLogic({
            shortId: SHORT_ID,
            mode: 'notebook',
            cachedNotebook: {
                ...cachedNotebook,
                content: buildMarkdownNotebookContent('# Markdown v2'),
            },
        })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        expect(logic.values.collabEnabled).toBe(false)
    })

    it('renders legacy notebooks as markdown when the markdown flag is enabled without marking them dirty', async () => {
        featureFlagLogic.actions.setFeatureFlags(
            [FEATURE_FLAGS.MARKDOWN_NOTEBOOKS, FEATURE_FLAGS.NOTEBOOKS_COLLABORATION],
            {
                [FEATURE_FLAGS.MARKDOWN_NOTEBOOKS]: true,
                [FEATURE_FLAGS.NOTEBOOKS_COLLABORATION]: true,
            }
        )

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        expect(logic.values.notebook?.content).toEqual(SAMPLE_DOC)
        expect(logic.values.content).toEqual(buildMarkdownNotebookContent('current'))
        expect(logic.values.localContent).toBeNull()
        expect(logic.values.syncStatus).toBe('synced')
        expect(logic.values.collabEnabled).toBe(false)
        expect(logic.values.markdownRealtimeEnabled).toBe(true)
        expect(apiUpdateSpy).not.toHaveBeenCalled()
        expect(apiMarkdownSaveSpy).not.toHaveBeenCalled()
    })

    it('reverts legacy history entries as markdown when the markdown flag is enabled', async () => {
        const historicalMarkdownContent = buildMarkdownNotebookContent('historical')
        apiMarkdownSaveSpy.mockResolvedValueOnce({
            ...cachedNotebook,
            version: 2,
            content: historicalMarkdownContent,
            text_content: 'historical',
        })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MARKDOWN_NOTEBOOKS], {
            [FEATURE_FLAGS.MARKDOWN_NOTEBOOKS]: true,
        })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.setEditor(stubEditor())
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        logic.actions.setPreviewContent(HISTORICAL_DOC)
        expect(logic.values.previewContent).toEqual(HISTORICAL_DOC)
        expect(logic.values.content).toEqual(historicalMarkdownContent)
        editorSetContent.mockClear()

        const contentToRestore = logic.values.content
        logic.actions.clearPreviewContent()
        logic.actions.setLocalContent(contentToRestore, true)
        logic.actions.setShowHistory(false)

        await expectLogic(logic)
            .delay(MARKDOWN_SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(editorSetContent).toHaveBeenCalledWith(historicalMarkdownContent)
        expect(apiMarkdownSaveSpy).toHaveBeenCalledWith(
            SHORT_ID,
            expect.objectContaining({
                content: historicalMarkdownContent,
                text_content: 'historical',
                version: 1,
            })
        )
        expect(apiUpdateSpy).not.toHaveBeenCalled()
    })

    it('clears stale legacy local content when loading a markdown v2 notebook', async () => {
        const markdownNotebook = {
            ...cachedNotebook,
            content: buildMarkdownNotebookContent('# Markdown v2'),
            text_content: '# Markdown v2',
        }
        jest.spyOn(api.notebooks, 'get').mockResolvedValueOnce(markdownNotebook as NotebookType)

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.setLocalContent(HISTORICAL_DOC)
        expect(logic.values.localContent).toEqual(HISTORICAL_DOC)

        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess', 'clearLocalContent']).toFinishAllListeners()

        expect(logic.values.notebook?.content).toEqual(markdownNotebook.content)
        expect(logic.values.localContent).toBeNull()

        await expectLogic(logic)
            .delay(SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(apiUpdateSpy).not.toHaveBeenCalled()
    })

    it('refreshes markdown v2 notebooks from the update stream', async () => {
        const baseContent = buildMarkdownNotebookContent('# Markdown v2')
        const updatedContent = buildMarkdownNotebookContent('# Markdown v2\n\nStreamed update')
        const streamNotebook = {
            ...cachedNotebook,
            content: baseContent,
            text_content: '# Markdown v2',
        }
        const updatedNotebook = {
            ...streamNotebook,
            version: 2,
            content: updatedContent,
            text_content: '# Markdown v2\n\nStreamed update',
        }
        type StreamOnMessage = (message: any) => void
        let streamOnMessage: StreamOnMessage | null = null

        jest.spyOn(api.notebooks, 'get')
            .mockResolvedValueOnce(streamNotebook as NotebookType)
            .mockResolvedValueOnce(updatedNotebook as NotebookType)
        jest.spyOn(api.notebooks, 'collabStream').mockImplementation(async (_shortId, { onMessage }) => {
            streamOnMessage = onMessage
        })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        if (!streamOnMessage) {
            throw new Error('expected markdown notebook update stream to be connected')
        }
        const onMessage: StreamOnMessage = streamOnMessage
        onMessage({
            id: '2-1',
            event: 'update',
            data: '{"type":"update","version":2}',
        })

        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        expect(logic.values.notebook?.version).toBe(2)
        expect(logic.values.notebook?.content).toEqual(updatedContent)
    })

    it('clears markdown local content after the save response updates notebook content', async () => {
        const baseContent = buildMarkdownNotebookContent('')
        const localContent = buildMarkdownNotebookContent(`# title

text`)
        const baseNotebook = {
            ...cachedNotebook,
            content: baseContent,
            text_content: '',
        }

        apiUpdateSpy.mockResolvedValueOnce({
            ...baseNotebook,
            version: 2,
            content: localContent,
            text_content: '# title\n\ntext',
        })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook: baseNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        logic.actions.setAutosavePaused(true)
        logic.actions.setLocalContent(localContent)

        await expectLogic(logic, () => {
            logic.actions.saveNotebook({ content: localContent, title: 'title' })
        })
            .toDispatchActions(['saveNotebook', 'saveNotebookSuccess', 'clearLocalContent'])
            .toFinishAllListeners()

        expect(logic.values.notebook?.content).toEqual(localContent)
        expect(logic.values.localContent).toBeNull()
    })

    it('keeps the local markdown draft and adopts fresh server content after a stale save conflict', async () => {
        const baseMarkdown = `# Markdown v2

Base paragraph`
        const localMarkdown = `# Markdown v2

Base paragraph with local edit`
        const remoteMarkdown = `# Markdown v2

Remote paragraph

Base paragraph`
        const baseMarkdownNotebook = {
            ...cachedNotebook,
            content: buildMarkdownNotebookContent(baseMarkdown),
            text_content: baseMarkdown,
        }
        const localContent = buildMarkdownNotebookContent(localMarkdown)
        const remoteNotebook = {
            ...baseMarkdownNotebook,
            version: 2,
            content: buildMarkdownNotebookContent(remoteMarkdown),
            text_content: remoteMarkdown,
        }

        apiUpdateSpy.mockRejectedValueOnce({ code: 'conflict' })
        jest.spyOn(api.notebooks, 'get').mockResolvedValueOnce(remoteNotebook)

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook: baseMarkdownNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        logic.actions.setAutosavePaused(true)
        logic.actions.setLocalContent(localContent)
        logic.actions.saveNotebook({ content: localContent, title: 'Test' })

        await expectLogic(logic).toDispatchActions(['saveNotebookSuccess']).toFinishAllListeners()

        expect(apiUpdateSpy).toHaveBeenCalledWith(
            SHORT_ID,
            expect.objectContaining({
                content: localContent,
                version: 1,
            })
        )
        // The fresh server content flows into the markdown editor's remote-merge path; the local
        // draft is kept so the editor can merge it and retry the save against the new version.
        expect(logic.values.notebook?.content).toEqual(remoteNotebook.content)
        expect(logic.values.localContent).toEqual(localContent)
        expect(logic.values.conflictWarningVisible).toBe(false)
    })

    it('shows the conflict warning when fresh server content cannot be loaded after a stale save conflict', async () => {
        const baseMarkdown = `# Markdown v2

Base paragraph`
        const localMarkdown = `# Markdown v2

Base paragraph with local edit`
        const baseMarkdownNotebook = {
            ...cachedNotebook,
            content: buildMarkdownNotebookContent(baseMarkdown),
            text_content: baseMarkdown,
        }
        const localContent = buildMarkdownNotebookContent(localMarkdown)

        apiUpdateSpy.mockRejectedValueOnce({ code: 'conflict' })
        jest.spyOn(api.notebooks, 'get').mockRejectedValueOnce(new Error('Network error'))

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook: baseMarkdownNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        logic.actions.setAutosavePaused(true)
        logic.actions.setLocalContent(localContent)

        await expectLogic(logic, () => {
            logic.actions.saveNotebook({ content: localContent, title: 'Test' })
        })
            .toDispatchActions(['clearLocalContent', 'showConflictWarning', 'saveNotebookSuccess'])
            .toFinishAllListeners()

        expect(logic.values.localContent).toBeNull()
        expect(logic.values.conflictWarningVisible).toBe(true)
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
                    on: jest.fn(),
                    off: jest.fn(),
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
