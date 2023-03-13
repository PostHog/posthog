import { actions, defaults, kea, key, listeners, path, props, reducers } from 'kea'
import { NodeType } from 'scenes/notebooks/Nodes/types'
import { Editor } from '@tiptap/core'
import type { notebookLogicType } from './notebookLogicType'

const START_CONTENT = `
<h2>Introducing Notebook!</h2>
<blockquote>This is experimental</blockquote>
<ph-query></ph-query>

<h3>An interesting recording I found</h3>
<p>This recording highlights perectly why...</p>
<br/>
<ph-recording sessionRecordingId="186cafad53bdcb-05999ec7735ee7-1f525634-16a7f0-186cafad53df8a"></ph-recording>
<ph-recording-playlist filters="{}"/>
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
        addNodeToNotebook: (type: NodeType, props: Record<string, any>) => ({ type, props }),
        syncContent: (content: string) => ({ content }),
    }),
    defaults({
        editor: null as Editor | null,
    }),
    reducers({
        content: [
            START_CONTENT as string,
            { persist: true },
            {
                syncContent: (_, { content }) => content,
            },
        ],

        editor: {
            setEditorRef: (_, { editor }) => editor,
        },
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
