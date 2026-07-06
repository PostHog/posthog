import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookNodeType, NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'
import { NOTEBOOK_AI_PRESENCE_CLIENT_ID, NOTEBOOK_AI_PRESENCE_NAME } from './notebookPresence'

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

    it('appends artifact markdown in insert-after-response mode', () => {
        logic.actions.handleMarkdownEditorChange(BASE_MARKDOWN)

        logic.actions.applyNotebookArtifactMarkdown(
            {
                content_type: 'notebook' as any,
                title: 'Generated',
                blocks: [{ type: 'markdown', content: 'Artifact paragraph' } as any],
            } as any,
            'inline-conversation-id',
            'insert-after-response'
        )

        const appliedMarkdown = (logic.values.localContent as any).content[0].attrs.markdown as string
        expect(appliedMarkdown).toEqual(`${BASE_MARKDOWN}\n\n# Generated\n\nArtifact paragraph`)
        expect(logic.values.markdownEditorDraft).toBeNull()
        expect(logic.values.autosavePaused).toBe(false)
    })

    it('applies full notebook artifacts without preserving inline AI placeholders', () => {
        logic.actions.handleMarkdownEditorChange(`${BASE_MARKDOWN}

Thinking...`)

        logic.actions.applyNotebookArtifactMarkdown(
            {
                content_type: 'notebook' as any,
                title: 'Cleaned notebook',
                blocks: [{ type: 'markdown', content: '# Cleaned notebook\n\nUseful content.' } as any],
            } as any,
            'inline-conversation-id',
            'replace'
        )

        const appliedMarkdown = (logic.values.localContent as any).content[0].attrs.markdown as string
        expect(appliedMarkdown).toEqual('# Cleaned notebook\n\nUseful content.')
        expect(appliedMarkdown).not.toContain('Thinking...')
        expect(logic.values.markdownEditorDraft).toBeNull()
        expect(logic.values.autosavePaused).toBe(false)
    })

    it('combines local and remote human presence participants', () => {
        logic.actions.handleRemotePresence({
            clientId: 'remote-client',
            userId: 42,
            userName: 'Remote User',
            version: 1,
            cursor: { node_index: 0 },
        })

        expect(logic.values.notebookPresenceParticipants).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    clientId: 'current-user',
                    userName: 'You',
                    isCurrentUser: true,
                }),
                expect.objectContaining({
                    clientId: 'remote-client',
                    userName: 'Remote User',
                }),
            ])
        )
        expect(logic.values.notebookPresenceParticipants).toHaveLength(2)
    })

    it('includes AI in notebook presence while the markdown AI cursor is active', () => {
        logic.actions.setMarkdownAIPresenceActive(true)

        expect(logic.values.notebookPresenceParticipants).toEqual([
            expect.objectContaining({
                clientId: 'current-user',
                userName: 'You',
                isCurrentUser: true,
            }),
            expect.objectContaining({
                clientId: NOTEBOOK_AI_PRESENCE_CLIENT_ID,
                userName: NOTEBOOK_AI_PRESENCE_NAME,
                isAI: true,
            }),
        ])

        logic.actions.setMarkdownAIPresenceActive(false)

        expect(logic.values.notebookPresenceParticipants).toHaveLength(1)
    })

    it('does not let an older save response roll back newer notebook content', () => {
        const version2Markdown = `${BASE_MARKDOWN}\n\nnewer save`
        const version3Markdown = `${BASE_MARKDOWN}\n\nnewest save`
        const version2Notebook = {
            ...cachedNotebook,
            version: 2,
            content: buildMarkdownNotebookContent(version2Markdown),
            text_content: version2Markdown,
        }
        const version3Notebook = {
            ...cachedNotebook,
            version: 3,
            content: buildMarkdownNotebookContent(version3Markdown),
            text_content: version3Markdown,
        }

        logic.actions.saveNotebookSuccess(version3Notebook)
        logic.actions.saveNotebookSuccess(version2Notebook)

        expect(logic.values.notebook?.version).toBe(3)
        expect(logic.values.notebook?.content).toEqual(version3Notebook.content)
    })

    it('keeps the highest notebook version during shuffled remote update bursts', () => {
        const shuffledRemoteNotebooks = [6, 4, 2, 3, 5, 7].map((version) => {
            const markdown = `${BASE_MARKDOWN}\n\nremote update ${version}`
            return {
                ...cachedNotebook,
                version,
                content: buildMarkdownNotebookContent(markdown),
                text_content: markdown,
            }
        })

        for (const notebook of shuffledRemoteNotebooks) {
            logic.actions.loadNotebookSuccess(notebook)
            logic.actions.applyRemoteNotebookContent(notebook.content, notebook.version)
        }

        const latestNotebook = shuffledRemoteNotebooks[shuffledRemoteNotebooks.length - 1]
        expect(logic.values.notebook?.version).toBe(latestNotebook.version)
        expect(logic.values.notebook?.content).toEqual(latestNotebook.content)
    })

    it('only surfaces the left column for markdown notebooks when history is open', () => {
        logic.unmount()
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.setLocalContent(buildMarkdownNotebookContent(BASE_MARKDOWN))

        const nodeLogic = {
            values: {
                nodeId: 'markdown-node',
                settingsPlacement: 'left',
            },
            props: {
                nodeType: NotebookNodeType.Experiment,
                attributes: { id: 1 },
            },
            actions: {
                selectNode: jest.fn(),
            },
        } as any

        logic.actions.setContainerSize('medium')
        logic.actions.registerNodeLogic('markdown-node', nodeLogic)
        logic.actions.setEditingNodeEditing('markdown-node', true)

        expect(logic.values.editingNodeLogics).toEqual([nodeLogic])
        expect(logic.values.editingNodeLogicsForLeft).toEqual([])
        expect(logic.values.isShowingLeftColumn).toBe(false)

        logic.actions.setShowHistory(true)

        expect(logic.values.isShowingLeftColumn).toBe(true)
    })
})
