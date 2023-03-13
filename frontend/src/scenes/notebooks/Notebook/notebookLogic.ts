import { actions, connect, defaults, kea, key, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { NodeType } from 'scenes/notebooks/Nodes/types'
import { Editor } from '@tiptap/core'
import type { notebookLogicType } from './notebookLogicType'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'

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

export const notebookLogic = kea<notebookLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookLogic']),
    key(() => 'global'),
    connect(() => ({
        actions: [notebookSidebarLogic, ['setFullScreen']],
    })),
    actions({
        setEditorRef: (editor: Editor) => ({ editor }),
        addNodeToNotebook: (type: NodeType, props: Record<string, any>) => ({ type, props }),
        setIsEditable: (isEditable: boolean) => ({ isEditable }),
        syncContent: (content: string) => ({ content }),
    }),
    defaults({
        editor: null as Editor | null,
        isEditable: true,
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
        isEditable: {
            setIsEditable: (_, { isEditable }) => isEditable,
        },
    }),
    listeners(({ values, actions }) => ({
        setEditorRef: ({ editor }) => {
            editor?.setEditable(values.isEditable)
        },

        setIsEditable: ({ isEditable }) => {
            values.editor?.setEditable(isEditable)
        },

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

            // Make notebook fullscreen
            actions.setFullScreen(true)
        },
    })),
])
