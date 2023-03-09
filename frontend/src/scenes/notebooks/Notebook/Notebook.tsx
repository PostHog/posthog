import { LemonButton } from '@posthog/lemon-ui'
import { useEditor, EditorContent, FloatingMenu } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { IconJournal, IconLock, IconLockOpen } from 'lib/lemon-ui/icons'
import { useEffect } from 'react'
import { QueryNode } from 'scenes/notebooks/Nodes/QueryNode'
import { InsightNode } from 'scenes/notebooks/Nodes/InsightNode'
import { RecordingNode } from 'scenes/notebooks/Nodes/RecordingNode'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { useActions, useValues } from 'kea'
import './Notebook.scss'

export type NotebookProps = {
    controls?: JSX.Element
    breadcrumbs?: string[]
}

export function Notebook({ controls, breadcrumbs }: NotebookProps): JSX.Element {
    const { content, isEditable } = useValues(notebookLogic)
    const { setEditorRef, setIsEditable, syncContent } = useActions(notebookLogic)

    const editor = useEditor({
        extensions: [StarterKit, InsightNode, QueryNode, RecordingNode],
        content,
        editorProps: {
            attributes: {
                class: 'Notebook',
            },
        },
        onUpdate: ({ editor }) => {
            syncContent(editor.getHTML())
        },
    })

    useEffect(() => {
        if (editor) {
            setEditorRef(editor)
        }
    }, [editor])

    return (
        <div className="border rounded bg-side flex-1 shadow overflow-hidden flex flex-col h-full">
            <header className="flex items-center justify-between gap-2 font-semibold shrink-0 p-2 border-b">
                <span>
                    <IconJournal />{' '}
                    {breadcrumbs?.map((breadcrumb, i) => (
                        <>
                            {breadcrumb}
                            {i < breadcrumbs.length - 1 && <span className="mx-1">/</span>}
                        </>
                    ))}
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
                    {controls}
                </span>
            </header>

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
    )
}
