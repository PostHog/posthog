import { actions, defaults, kea, key, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { NodeType } from 'scenes/notebooks/Nodes/types'
import { Editor } from '@tiptap/core'
import type { notebookLogicType } from './notebookLogicType'

const START_CONTENT = `
<h2>Introducing Notebook!</h2>
<blockquote>This is experimental</blockquote>
<ph-query></ph-query>

<ph-insight shortId="OlmLXv6Q"></ph-insight>

<h3>An interesting recording I found</h3>

<p>This recording highlights perectly why...</p>
<br/>
<ph-recording sessionRecordingId="186c620122516e6-0ebf2e4cc8b8da-1f525634-16a7f0-186c62012262dfa"></ph-recording>
`

export const notebookLogic = kea<notebookLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookLogic']),
    key(() => 'global'),
    actions({
        setEditorRef: (editor: Editor) => ({ editor }),
        addNodeToNotebook: (type: NodeType, props: Record<string, any>) => ({ type, props }),
        setIsEditable: (isEditable: boolean) => ({ isEditable }),
        syncContent: (content: string) => ({ content }),
    }),
    defaults({
        editor: null as Editor | null,
        content: START_CONTENT as string,
        isEditable: true,
    }),
    loaders(() => ({
        content: {
            syncContent: ({ content }) => content,
        },
    })),
    reducers({
        editor: {
            setEditorRef: (_, { editor }) => editor,
        },
        isEditable: {
            setIsEditable: (_, { isEditable }) => isEditable,
        },
    }),
    listeners(({ values }) => ({
        addNodeToNotebook: ({ type, props }) => {
            if (!values.editor) {
                return
            }

            let evalHTML = ''

            if (type === NodeType.Recording) {
                evalHTML = `<${type} sessionRecordingId="${props.sessionRecordingId}"/>`
            }

            values.editor.chain().focus().insertContent(evalHTML).run()
        },
    })),
])
