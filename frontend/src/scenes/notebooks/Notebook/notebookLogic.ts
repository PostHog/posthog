import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'

import type { notebookLogicType } from './notebookLogicType'
import { loaders } from 'kea-loaders'
import { notebooksListLogic } from './notebooksListLogic'
import { NotebookSyncStatus, NotebookType } from '~/types'

// NOTE: Annoyingly, if we import this then kea logic typegen generates two imports and fails so we reimport it from a utils file
import { JSONContent, Editor } from './utils'
import api from 'lib/api'

const SYNC_DELAY = 1000

export type NotebookLogicProps = {
    shortId: string
}

export const notebookLogic = kea<notebookLogicType>([
    props({} as NotebookLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookLogic', key]),
    key(({ shortId }) => shortId),
    connect({
        values: [notebooksListLogic, ['scratchpadNotebook']],
        actions: [notebooksListLogic, ['receiveNotebookUpdate']],
    }),
    actions({
        setEditorRef: (editor: Editor) => ({ editor }),
        addNodeToNotebook: (type: NotebookNodeType, props: Record<string, any>) => ({ type, props }),
        onEditorUpdate: true,
        setLocalContent: (jsonContent: JSONContent) => ({ jsonContent }),
        setReady: true,
        loadNotebook: true,
        saveNotebook: (notebook: Pick<NotebookType, 'content' | 'title'>) => ({ notebook }),
    }),
    reducers({
        localContent: [
            null as JSONContent | null,
            { persist: true },
            {
                setLocalContent: (_, { jsonContent }) => jsonContent,
                loadNotebookSuccess: (state, { notebook }) => {
                    if (state === notebook?.content) {
                        return null
                    }
                    return state
                },
                saveNotebookSuccess: (state, { notebook }) => {
                    if (state === notebook?.content) {
                        return null
                    }
                    return state
                },
            },
        ],
        editor: [
            null as Editor | null,
            {
                setEditorRef: (_, { editor }) => editor,
            },
        ],

        ready: [
            false,
            {
                setReady: () => true,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        notebook: [
            undefined as NotebookType | undefined,
            {
                loadNotebook: async () => {
                    // NOTE: This is all hacky and temporary until we have a backend
                    let response: NotebookType | undefined

                    if (props.shortId === 'scratchpad') {
                        response = {
                            ...values.scratchpadNotebook,
                            content: {},
                            version: 0,
                        }
                    } else {
                        response = await api.notebooks.get(props.shortId)
                    }

                    if (!response) {
                        throw new Error('Notebook not found')
                    }

                    if (!values.notebook) {
                        // If this is the first load we need to override the content fully
                        values.editor?.commands.setContent(response.content)
                    }

                    return response
                },

                saveNotebook: async ({ notebook }) => {
                    if (!values.notebook) {
                        return
                    }
                    const response = await api.notebooks.update(values.notebook.short_id, {
                        version: values.notebook.version,
                        content: notebook.content,
                        title: notebook.title,
                    })

                    return response
                },
            },
        ],
    })),
    selectors({
        isLocalOnly: [() => [(_, props) => props], (props): boolean => props.id === 'scratchpad'],
        content: [
            (s) => [s.notebook, s.localContent],
            (notebook, localContent): JSONContent | undefined => {
                // We use the local content is set otherwise the notebook content
                return localContent || notebook?.content
            },
        ],
        title: [
            (s) => [s.notebook, s.content],
            (notebook, content): string => {
                const contentTitle = content?.content?.[0].content?.[0].text || 'Untitled'
                return contentTitle || notebook?.title || 'Untitled'
            },
        ],

        syncStatus: [
            (s) => [s.notebook, s.notebookLoading, s.localContent, s.isLocalOnly],
            (notebook, notebookLoading, localContent, isLocalOnly): NotebookSyncStatus | undefined => {
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
    listeners(({ values, actions }) => ({
        addNodeToNotebook: ({ type, props }) => {
            if (!values.editor) {
                return
            }

            values.editor
                .chain()
                .focus()
                .insertContent({
                    type,
                    attrs: props,
                })
                .run()
        },

        setLocalContent: async (_, breakpoint) => {
            await breakpoint(SYNC_DELAY)
            if (!values.isLocalOnly && values.content) {
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
            // TODO: We might want a more efficient comparison here
            if (JSON.stringify(jsonContent) !== JSON.stringify(values.content)) {
                actions.setLocalContent(jsonContent)
            }
        },

        saveNotebookSuccess: ({ notebook }) => {
            if (notebook) {
                actions.receiveNotebookUpdate(notebook)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadNotebook()
        setTimeout(() => {
            actions.setReady()
        }, 500)
    }),
])
