import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'

jest.mock('./migrations/migrate', () => {
    const actual = jest.requireActual('./migrations/migrate')
    return {
        ...actual,
        migrate: jest.fn(async (notebook) => notebook),
    }
})

const SHORT_ID = 'test-markdown-editor'
const BASE_MARKDOWN = `# Title

Base paragraph`

const cachedNotebook: NotebookType = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Test',
    content: buildMarkdownNotebookContent(BASE_MARKDOWN),
    text_content: BASE_MARKDOWN,
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
} as unknown as NotebookType

describe('notebookLogic markdown editor state', () => {
    let logic: ReturnType<typeof notebookLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, cachedNotebook],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/kernel/status/`]: () => [200, { backend: null }],
            },
        })
        // localContent is a persisted reducer — clear it so tests don't leak into each other
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('applies editor changes to local content when no interaction is active', () => {
        const nextMarkdown = `${BASE_MARKDOWN} edited`

        logic.actions.handleMarkdownEditorChange(nextMarkdown)

        expect(logic.values.localContent).toEqual(buildMarkdownNotebookContent(nextMarkdown))
        expect(logic.values.markdownEditorValue).toEqual(nextMarkdown)
        expect(logic.values.markdownEditorDraft).toBeNull()
    })

    it('ignores editor changes that match the current content', () => {
        expect(logic.values.markdownEditorMarkdown).toEqual(BASE_MARKDOWN)

        logic.actions.handleMarkdownEditorChange(BASE_MARKDOWN)

        expect(logic.values.localContent).toBeNull()
    })

    it('buffers editor changes while an interaction is active and flushes them when it ends', () => {
        const bufferedMarkdown = `${BASE_MARKDOWN} typed during interaction`

        logic.actions.setMarkdownEditorInteractionActive(true)

        expect(logic.values.autosavePaused).toBe(true)
        expect(logic.values.markdownEditorDraft).toEqual(BASE_MARKDOWN)

        logic.actions.handleMarkdownEditorChange(bufferedMarkdown)

        // The edit stays out of localContent (no autosave) but the editor keeps rendering it.
        expect(logic.values.localContent).toBeNull()
        expect(logic.values.markdownEditorValue).toEqual(bufferedMarkdown)

        logic.actions.setMarkdownEditorInteractionActive(false)

        expect(logic.values.autosavePaused).toBe(false)
        expect(logic.values.markdownEditorDraft).toBeNull()
        expect(logic.values.markdownEditorBuffer).toBeNull()
        expect(logic.values.localContent).toEqual(buildMarkdownNotebookContent(bufferedMarkdown))
        expect(logic.values.markdownEditorValue).toEqual(bufferedMarkdown)
    })

    it('keeps the editor value frozen during an interaction without buffered edits', () => {
        logic.actions.setMarkdownEditorInteractionActive(true)
        logic.actions.setMarkdownEditorInteractionActive(false)

        expect(logic.values.localContent).toBeNull()
        expect(logic.values.markdownEditorDraft).toBeNull()
        expect(logic.values.markdownEditorValue).toEqual(BASE_MARKDOWN)
        expect(logic.values.autosavePaused).toBe(false)
    })

    it('applies notebook artifact markdown while preserving the chat marker', () => {
        const chatId = '10000000-1000-4000-8000-100000000001'
        const withChatMarkdown = `${BASE_MARKDOWN}

<Chat id="${chatId}" />`
        logic.actions.handleMarkdownEditorChange(withChatMarkdown)

        logic.actions.applyNotebookArtifactMarkdown(
            {
                content_type: 'notebook' as any,
                title: 'Generated',
                blocks: [{ type: 'markdown', content: 'Artifact paragraph' } as any],
            } as any,
            chatId
        )

        const appliedMarkdown = (logic.values.localContent as any).content[0].attrs.markdown as string
        expect(appliedMarkdown).toContain('Artifact paragraph')
        expect(appliedMarkdown).toContain(`<Chat id="${chatId}" />`)
        expect(logic.values.markdownEditorDraft).toBeNull()
        expect(logic.values.autosavePaused).toBe(false)
    })
})
