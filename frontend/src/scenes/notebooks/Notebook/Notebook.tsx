import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useEditor, EditorContent, FloatingMenu } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { IconChevronRight, IconJournal, IconLock, IconLockOpen } from 'lib/lemon-ui/icons'
import { useEffect, useState } from 'react'
import { QueryNode } from 'scenes/notebooks/Nodes/QueryNode'
import { InsightNode } from 'scenes/notebooks/Nodes/InsightNode'
import { RecordingNode } from 'scenes/notebooks/Nodes/RecordingNode'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { useValues } from 'kea'

export function Notebook(): JSX.Element {
    const { content } = useValues(notebookLogic)

    const editor = useEditor({
        extensions: [StarterKit, InsightNode, QueryNode, RecordingNode],
        content,
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
        <div className="h-full p-2 flex flex-col">
            <div className="border rounded bg-side flex-1 p-3 shadow overflow-y-auto">
                <header className="flex items-center justify-between gap-2 font-semibold shrink-0">
                    <span>
                        <IconJournal /> Notebook
                    </span>
                    <span className="flex gap-2">
                        <LemonButton
                            size="small"
                            onClick={() => setIsEditable(!isEditable)}
                            status="primary-alt"
                            type={!isEditable ? 'primary' : undefined}
                            noPadding
                        >
                            <div className="m-1">{!isEditable ? <IconLock /> : <IconLockOpen />}</div>
                        </LemonButton>
                        <LemonButton size="small" onClick={() => alert('TODO!')} status="primary-alt" noPadding>
                            <IconChevronRight className="text-lg" />
                        </LemonButton>
                    </span>
                </header>
                <LemonDivider dashed />

                {editor && (
                    <FloatingMenu editor={editor} tippyOptions={{ duration: 100 }} className="flex items-center gap-2">
                        <LemonButton
                            size="small"
                            status="primary-alt"
                            onClick={() => editor.chain().focus().insertContent('<ph-query />').run()}
                        >
                            Query
                        </LemonButton>

                        <LemonButton
                            size="small"
                            status="primary-alt"
                            onClick={() => editor.chain().focus().insertContent('<ph-playlist />').run()}
                        >
                            Recordings
                        </LemonButton>

                        <LemonButton
                            size="small"
                            status="primary-alt"
                            onClick={() => editor.chain().focus().insertContent('<ph-embed />').run()}
                        >
                            Embed
                        </LemonButton>
                    </FloatingMenu>
                )}

                <EditorContent editor={editor} className="flex-1 overflow-y-auto" />
            </div>
        </div>
    )
}
