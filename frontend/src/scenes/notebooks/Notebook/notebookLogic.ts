import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'

import type { notebookLogicType } from './notebookLogicType'

// NOTE: Annoyingly, if we import this then kea logic typegen generates two imports and fails so we jusz use Any
// import type { Editor } from '@tiptap/core'

export type Editor = any

const START_CONTENT = `
<h2>Introducing Notebook!</h2>
<blockquote>This is an experimental feature allowing you to bring multiple items from across PostHog into one place</blockquote>
<ph-query></ph-query>

`

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
    }),
    reducers({
        content: [
            START_CONTENT as string,
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
])
