import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'

import type { notebookLogicType } from './notebookLogicType'
import { JSONContent } from '@tiptap/core'
import { loaders } from 'kea-loaders'
import { notebooksListLogic } from './notebooksListLogic'
import { NotebookListItemType, NotebookType } from '~/types'
import { delay } from 'lib/utils'

// NOTE: Annoyingly, if we import this then kea logic typegen generates two imports and fails so we jusz use Any
// import type { Editor } from '@tiptap/core'

const SYNC_DELAY = 1000

export type Editor = any

export type NotebookLogicProps = {
    id: string
}

export const notebookLogic = kea<notebookLogicType>([
    props({} as NotebookLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookLogic', key]),
    key(({ id }) => id),
    connect({
        values: [notebooksListLogic, ['localNotebooks', 'scratchpadNotebook']],
    }),
    actions({
        setEditorRef: (editor: Editor) => ({ editor }),
        addNodeToNotebook: (type: NotebookNodeType, props: Record<string, any>) => ({ type, props }),
        onEditorUpdate: true,
        setLocalContent: (jsonContent: JSONContent) => ({ jsonContent }),
        setReady: true,
        loadNotebook: true,
        saveNotebookContent: (content: JSONContent) => ({ content }),
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
                saveNotebookContentSuccess: (state, { notebook }) => {
                    if (state === notebook?.content) {
                        return null
                    }
                    return state
                },
            },
        ],
        mockRemoteContent: [
            null as JSONContent | null,
            { persist: true },
            {
                loadNotebookSuccess: (_, { notebook }) => notebook.content,
                saveNotebookContentSuccess: (_, { notebook }) => notebook?.content ?? null,
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
                    let found: NotebookListItemType | undefined

                    await delay(1000)

                    if (props.id === 'scratchpad') {
                        found = values.scratchpadNotebook
                    } else {
                        found = values.localNotebooks.find((x) => x.id === props.id)
                    }

                    if (!found) {
                        throw new Error('Notebook not found')
                    }

                    const response = {
                        ...found,
                        content: values.mockRemoteContent,
                    }

                    if (!values.notebook) {
                        // If this is the first load we need to override the content fully
                        values.editor?.commands.setContent(response.content)
                    }

                    return response
                },

                saveNotebookContent: async ({ content }) => {
                    if (!values.notebook) {
                        return
                    }
                    await delay(1000)

                    console.log('saving notebook content!')

                    return {
                        ...values.notebook,
                        content,
                    }
                },
            },
        ],
    })),
    selectors({
        content: [
            (s) => [s.notebook, s.localContent],
            (notebook, localContent): JSONContent | undefined => {
                // We use the local content is set otherwise the notebook content
                return localContent || notebook?.content
            },
        ],

        syncStatus: [
            (s) => [s.notebook, s.notebookLoading, s.localContent],
            (notebook, notebookLoading, localContent): 'synced' | 'saving' | 'unsaved' | undefined => {
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

        setLocalContent: async ({ jsonContent }, breakpoint) => {
            await breakpoint(SYNC_DELAY)
            actions.saveNotebookContent(jsonContent)
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
    })),

    afterMount(({ actions }) => {
        actions.loadNotebook()
        setTimeout(() => {
            actions.setReady()
        }, 500)
    }),
])
