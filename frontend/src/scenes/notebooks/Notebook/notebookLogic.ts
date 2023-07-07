import { actions, connect, kea, key, listeners, path, props, reducers, selectors, sharedListeners } from 'kea'
import type { notebookLogicType } from './notebookLogicType'
import { loaders } from 'kea-loaders'
import { handleNotebookCreation, notebooksListLogic, SCRATCHPAD_NOTEBOOK } from './notebooksListLogic'
import { NotebookSyncStatus, NotebookType } from '~/types'

// NOTE: Annoyingly, if we import this then kea logic typegen generates two imports and fails so we reimport it from a utils file
import { JSONContent, NotebookEditor } from './utils'
import api from 'lib/api'
import posthog from 'posthog-js'
import { downloadFile, slugify } from 'lib/utils'
import { lemonToast } from '@posthog/lemon-ui'

const SYNC_DELAY = 1000

export type NotebookLogicProps = {
    shortId: string
}

export const notebookLogic = kea<notebookLogicType>([
    props({} as NotebookLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookLogic', key]),
    key(({ shortId }) => shortId),
    connect({
        values: [notebooksListLogic, ['scratchpadNotebook', 'notebookTemplates']],
        actions: [notebooksListLogic, ['receiveNotebookUpdate']],
    }),
    actions({
        setEditor: (editor: NotebookEditor) => ({ editor }),
        onEditorUpdate: true,
        setLocalContent: (jsonContent: JSONContent) => ({ jsonContent }),
        clearLocalContent: true,
        setReady: true,
        loadNotebook: true,
        saveNotebook: (notebook: Pick<NotebookType, 'content' | 'title'>) => ({ notebook }),
        exportJSON: true,
        showConflictWarning: true,
    }),
    reducers({
        localContent: [
            null as JSONContent | null,
            { persist: true },
            {
                setLocalContent: (_, { jsonContent }) => jsonContent,
                clearLocalContent: () => null,
            },
        ],
        editor: [
            null as NotebookEditor | null,
            {
                setEditor: (_, { editor }) => editor,
            },
        ],
        ready: [
            false,
            {
                setReady: () => true,
            },
        ],
        conflictWarningVisible: [
            false,
            {
                showConflictWarning: () => true,
                loadNotebookSuccess: () => false,
            },
        ],
    }),
    loaders(({ values, props, actions }) => ({
        notebook: [
            null as NotebookType | null,
            {
                loadNotebook: async () => {
                    // NOTE: This is all hacky and temporary until we have a backend
                    let response: NotebookType | null

                    if (props.shortId === SCRATCHPAD_NOTEBOOK.short_id) {
                        response = {
                            ...values.scratchpadNotebook,
                            content: {},
                            version: 0,
                        }
                    } else if (props.shortId.startsWith('template-')) {
                        response =
                            values.notebookTemplates.find((template) => template.short_id === props.shortId) || null
                    } else {
                        response = await api.notebooks.get(props.shortId)
                    }

                    if (!response) {
                        throw new Error('Notebook not found')
                    }

                    if (!values.notebook) {
                        // If this is the first load we need to override the content fully
                        values.editor?.setContent(response.content)
                    }

                    return response
                },

                saveNotebook: async ({ notebook }) => {
                    if (!values.notebook) {
                        return values.notebook
                    }

                    try {
                        const response = await api.notebooks.update(values.notebook.short_id, {
                            version: values.notebook.version,
                            content: notebook.content,
                            title: notebook.title,
                        })

                        // If the object is identical then no edits were made, so we can safely clear the local changes
                        if (notebook.content === values.localContent) {
                            actions.clearLocalContent()
                        }

                        return response
                    } catch (error: any) {
                        if (error.code === 'conflict') {
                            actions.showConflictWarning()
                            return null
                        } else {
                            throw error
                        }
                    }
                },
            },
        ],

        newNotebook: [
            null as NotebookType | null,
            {
                duplicateNotebook: async () => {
                    if (!values.notebook) {
                        return null
                    }

                    // We use the local content if set otherwise the notebook content. That way it supports templates, scratchpad etc.
                    const response = await api.notebooks.create({
                        content: values.content || values.notebook.content,
                        title: values.title || values.notebook.title,
                    })

                    posthog.capture(`notebook duplicated`, {
                        short_id: response.short_id,
                    })

                    const source = values.notebook.short_id === 'scratchpad' ? 'Scratchpad' : 'Template'
                    lemonToast.success(`Notebook created from ${source}!`)

                    if (values.notebook.short_id === 'scratchpad') {
                        // If duplicating the scratchpad, we assume they don't want the scratchpad content anymore
                        actions.clearLocalContent()
                    }

                    handleNotebookCreation(response)

                    return response
                },
            },
        ],
    })),
    selectors({
        shortId: [() => [(_, props) => props], (props): string => props.shortId],
        isLocalOnly: [() => [(_, props) => props], (props): boolean => props.shortId === 'scratchpad'],
        content: [
            (s) => [s.notebook, s.localContent],
            (notebook, localContent): JSONContent => {
                // We use the local content is set otherwise the notebook content
                return localContent || notebook?.content || []
            },
        ],
        title: [
            (s) => [s.notebook, s.content],
            (notebook, content): string => {
                const contentTitle = content?.content?.[0].content?.[0].text || 'Untitled'
                return contentTitle || notebook?.title || 'Untitled'
            },
        ],

        isEmpty: [
            (s) => [s.editor, s.content],
            (editor: NotebookEditor): boolean => {
                return editor?.isEmpty() || false
            },
        ],

        syncStatus: [
            (s) => [s.notebook, s.notebookLoading, s.localContent, s.isLocalOnly],
            (notebook, notebookLoading, localContent, isLocalOnly): NotebookSyncStatus => {
                if (notebook?.is_template) {
                    return 'synced'
                }

                if (isLocalOnly) {
                    return 'local'
                }
                if (!notebook || !localContent) {
                    return 'synced'
                }

                if (notebookLoading) {
                    return 'saving'
                }

                return 'unsaved'
            },
        ],
    }),
    sharedListeners(({ values, actions }) => ({
        onNotebookChange: () => {
            // Keep the list logic up to date with any changes
            if (values.notebook && values.notebook.short_id !== SCRATCHPAD_NOTEBOOK.short_id) {
                actions.receiveNotebookUpdate(values.notebook)
            }
        },
    })),
    listeners(({ values, actions, sharedListeners }) => ({
        setLocalContent: async (_, breakpoint) => {
            await breakpoint(SYNC_DELAY)

            posthog.capture('notebook content changed', {
                short_id: values.notebook?.short_id,
            })

            if (!values.isLocalOnly && values.content && !values.notebookLoading) {
                actions.saveNotebook({
                    content: values.content,
                    title: values.title,
                })
            }
        },

        onEditorUpdate: () => {
            if (!values.editor || !values.notebook) {
                return
            }
            const jsonContent = values.editor.getJSON()
            actions.setLocalContent(jsonContent)
        },

        saveNotebookSuccess: sharedListeners.onNotebookChange,
        loadNotebookSuccess: sharedListeners.onNotebookChange,

        exportJSON: () => {
            const file = new File(
                [JSON.stringify(values.editor?.getJSON())],
                `${slugify(values.title ?? 'untitled')}.ph-notebook.json`,
                { type: 'application/json' }
            )

            downloadFile(file)
        },
    })),
])
