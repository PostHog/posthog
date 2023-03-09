import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { IconLock, IconLockOpen } from 'lib/lemon-ui/icons'
import { useEffect, useState } from 'react'
import InsightNode from '../Nodes/InsightNode'

import './Notebook.scss'

const START_CONTENT = `
<h2>Introducing Notebook!</h2>
<blockquote>This is experimental</blockquote>

<ph-insight></ph-insight>

`

export function Notebook(): JSX.Element {
    const editor = useEditor({
        extensions: [StarterKit, InsightNode],
        content: START_CONTENT,
        editorProps: {
            attributes: {
                class: 'Notebook prose h-full',
            },
        },
    })

    const [isEditable, setIsEditable] = useState(true)

    useEffect(() => {
        if (editor) {
            editor.setEditable(isEditable)
        }
    }, [isEditable, editor])

    return (
        <div className="border-l bg-side h-full p-2 flex flex-col">
            <header className="flex items-center justify-between gap-2 uppercase font-semibold shrink-0">
                <span>Notebook</span>
                <span className="flex gap-2">
                    <LemonButton
                        size="small"
                        onClick={() => setIsEditable(!isEditable)}
                        status="primary-alt"
                        type={!isEditable ? 'primary' : undefined}
                    >
                        {!isEditable ? <IconLock /> : <IconLockOpen />}
                    </LemonButton>
                </span>
            </header>
            <LemonDivider dashed />

            <EditorContent editor={editor} className="flex-1 overflow-y-auto" />
        </div>
    )
}
