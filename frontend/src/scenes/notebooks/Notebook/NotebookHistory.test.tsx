import { JSONContent } from '@tiptap/core'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, ActivityScope } from '~/types'

import { NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
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
    let apiUpdateSpy: jest.SpyInstance
    let apiMarkdownSaveSpy: jest.SpyInstance
    let apiActivityListLegacySpy: jest.SpyInstance
    let historyLogic: ReturnType<typeof activityLogLogic.build> | null

    beforeEach(() => {
        localStorage.clear()
        historyLogic = null
        useMocks({
            get: {
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, cachedNotebook],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/`]: () => [200, cachedNotebook],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/kernel/status/`]: () => [200, { backend: null }],
            },
        })
        initKeaTests()

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
    })

    it('opening preview: setPreviewContent updates the reducer, no save dispatched', async () => {
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()

        // user clicks a history entry
        logic.actions.setPreviewContent(HISTORICAL_DOC)
        // wait past debounce so any save would have fired
        await expectLogic(logic)
            .delay(SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(logic.values.previewContent).toEqual(HISTORICAL_DOC)
        // the preview renders through the markdown converter
        expect(logic.values.content).toEqual(buildMarkdownNotebookContent('historical'))
        expect(logic.values.localContent).toBeNull()
        // previewing is non-mutating
        expect(apiUpdateSpy).not.toHaveBeenCalled()
        expect(apiMarkdownSaveSpy).not.toHaveBeenCalled()
    })

    it('does not persist content edits made while previewing a historical revision', async () => {
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()

        logic.actions.setPreviewContent(HISTORICAL_DOC)
        logic.actions.setLocalContent(buildMarkdownNotebookContent('draft while previewing'))

        await expectLogic(logic)
            .delay(SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(logic.values.previewContent).toEqual(HISTORICAL_DOC)
        expect(apiUpdateSpy).not.toHaveBeenCalled()
        expect(apiMarkdownSaveSpy).not.toHaveBeenCalled()
    })

    it('saves through the pending content debounce after autosave resumes', async () => {
        const editedContent = buildMarkdownNotebookContent('historical')
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        logic.actions.setAutosavePaused(true)
        logic.actions.setLocalContent(editedContent)
        logic.actions.setAutosavePaused(false)
        expect(apiMarkdownSaveSpy).not.toHaveBeenCalled()

        await expectLogic(logic)
            .delay(SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(apiMarkdownSaveSpy).toHaveBeenCalledTimes(1)
        expect(apiMarkdownSaveSpy).toHaveBeenCalledWith(
            SHORT_ID,
            expect.objectContaining({ content: editedContent, version: 1 })
        )
    })

    it('persists the legacy to markdown conversion on the first edit', async () => {
        const convertedContent = buildMarkdownNotebookContent(`# Test

converted`)
        apiMarkdownSaveSpy.mockResolvedValueOnce({
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
            .delay(MARKDOWN_SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(apiMarkdownSaveSpy).toHaveBeenCalledWith(
            SHORT_ID,
            expect.objectContaining({
                content: convertedContent,
                text_content: '# Test\n\nconverted',
                version: 1,
            })
        )
        expect(apiUpdateSpy).not.toHaveBeenCalled()
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
            logic.actions.saveNotebook({ content: buildMarkdownNotebookContent('historical'), title: 'Test' })
        })
            .toDispatchActions(['saveNotebookSuccess'])
            .toFinishAllListeners()
        await expectLogic(historyLogic).toFinishAllListeners()

        expect(apiActivityListLegacySpy).toHaveBeenCalledWith({ scope: [ActivityScope.NOTEBOOK], id: SHORT_ID }, 1)
    })

    it('renders legacy notebooks as markdown without marking them dirty', async () => {
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        expect(logic.values.notebook?.content).toEqual(SAMPLE_DOC)
        expect(logic.values.content).toEqual(buildMarkdownNotebookContent('current'))
        expect(logic.values.localContent).toBeNull()
        expect(logic.values.syncStatus).toBe('synced')
        expect(logic.values.markdownRealtimeEnabled).toBe(true)
        expect(apiUpdateSpy).not.toHaveBeenCalled()
        expect(apiMarkdownSaveSpy).not.toHaveBeenCalled()
    })

    it('reverts legacy history entries as markdown', async () => {
        const historicalMarkdownContent = buildMarkdownNotebookContent('historical')
        apiMarkdownSaveSpy.mockResolvedValueOnce({
            ...cachedNotebook,
            version: 2,
            content: historicalMarkdownContent,
            text_content: 'historical',
        })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        logic.actions.setPreviewContent(HISTORICAL_DOC)
        expect(logic.values.previewContent).toEqual(HISTORICAL_DOC)
        expect(logic.values.content).toEqual(historicalMarkdownContent)

        // user clicks Revert — mirror the action sequence in NotebookHistoryWarning.onRevert
        const contentToRestore = logic.values.content
        logic.actions.clearPreviewContent()
        logic.actions.setLocalContent(contentToRestore)
        logic.actions.setShowHistory(false)

        await expectLogic(logic)
            .delay(MARKDOWN_SYNC_DELAY + 100)
            .toFinishAllListeners()

        expect(logic.values.previewContent).toBeNull()
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

        apiMarkdownSaveSpy.mockResolvedValueOnce({
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

    it('merges missed remote diffs and retries when a save hits a stale version', async () => {
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

        // First save is rejected as stale with no replayable diffs (410): the logic reloads
        // and keeps the local draft so the editor can merge and retry.
        apiMarkdownSaveSpy.mockRejectedValueOnce({ status: 410 })
        const remoteMarkdown = `# Markdown v2

Remote paragraph

Base paragraph`
        const remoteNotebook = {
            ...baseMarkdownNotebook,
            version: 2,
            content: buildMarkdownNotebookContent(remoteMarkdown),
            text_content: remoteMarkdown,
        }
        jest.spyOn(api.notebooks, 'get')
            .mockResolvedValueOnce(baseMarkdownNotebook as NotebookType)
            .mockResolvedValueOnce(remoteNotebook as NotebookType)

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        logic.actions.setAutosavePaused(true)
        logic.actions.setLocalContent(localContent)
        logic.actions.saveNotebook({ content: localContent, title: 'Test' })

        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()

        // The fresh server content flows into the markdown editor's remote-merge path; the local
        // draft is kept so the editor can merge it and retry the save against the new version.
        expect(logic.values.notebook?.content).toEqual(remoteNotebook.content)
        expect(logic.values.localContent).toEqual(localContent)
    })
})
