import { LemonDivider } from '@posthog/lemon-ui'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import InsightNode from 'scenes/notebooks/Nodes/InsightNode'
import RecordingNode from 'scenes/notebooks/Nodes/RecordingNode'

import './Notebook.scss'

const START_CONTENT = `
<h2>Introducing Notebook!</h2>
<blockquote>This is experimental</blockquote>

<ph-insight></ph-insight>
<ph-recording></ph-recording>
`

export function Notebook(): JSX.Element {
    const editor = useEditor({
        extensions: [StarterKit, InsightNode, RecordingNode],
        content: START_CONTENT,
        editorProps: {
            attributes: {
                class: 'Notebook prose h-full',
            },
        },
    })

    return (
        <div className="border-l bg-side h-full p-2 flex flex-col">
            <header className="flex items-center space-between uppercase font-semibold shrink-0">Notebook</header>
            <LemonDivider dashed />

            <EditorContent editor={editor} className="flex-1 overflow-y-auto" />
        </div>
    )
}
