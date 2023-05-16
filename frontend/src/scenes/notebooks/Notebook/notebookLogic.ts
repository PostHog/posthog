import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'

import type { notebookLogicType } from './notebookLogicType'

// NOTE: Annoyingly, if we import this then kea logic typegen generates two imports and fails so we jusz use Any
// import type { Editor } from '@tiptap/core'

export type Editor = any

export type NotebookLogicProps = {
    id: string
}

export const notebookLogic = kea<notebookLogicType>([
    props({} as NotebookLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookLogic', key]),
    key(({ id }) => id),
    actions({
        setEditorRef: (editor: Editor) => ({ editor }),
        addNodeToNotebook: (type: NotebookNodeType, props: Record<string, any>) => ({ type, props }),
        syncContent: (content: string) => ({ content }),
        setReady: true,
    }),
    reducers({
        content: [
            '' as string,
            { persist: true },
            {
                syncContent: (_, { content }) => content,
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
    selectors({
        // TODO: This isn't used yet
        editable: [(s) => [s.ready], (ready): boolean => ready],
    }),
    listeners(({ values }) => ({
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
    })),

    afterMount(({ actions }) => {
        setTimeout(() => {
            actions.setReady()
        }, 500)
    }),
])
