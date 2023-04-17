import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useEffect } from 'react'
import { QueryNode } from 'scenes/notebooks/Nodes/QueryNode'
import { InsightNode } from 'scenes/notebooks/Nodes/InsightNode'
import { RecordingNode } from 'scenes/notebooks/Nodes/RecordingNode'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { useActions, useValues } from 'kea'
import './Notebook.scss'
import { RecordingPlaylistNode } from 'scenes/notebooks/Nodes/RecordingPlaylistNode'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import MonacoEditor from '@monaco-editor/react'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { FeatureFlagNode } from '../Nodes/FeatureFlagNode'

export type NotebookProps = {
    id: string
    sourceMode?: boolean
    editable?: boolean
}

export function Notebook({ id, sourceMode, editable = false }: NotebookProps): JSX.Element {
    const logic = notebookLogic({ id })
    const { content } = useValues(logic)
    const { setEditorRef, syncContent } = useActions(logic)

    const editor = useEditor({
        extensions: [StarterKit, InsightNode, QueryNode, RecordingNode, RecordingPlaylistNode, FeatureFlagNode],
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

    useEffect(() => {
        editor?.setEditable(editable)
    }, [editable, editor])

    return (
        <div className="flex-1 overflow-hidden flex flex-col h-full">
            {/* {editor && (
                <FloatingMenu editor={editor} tippyOptions={{ duration: 100 }} className="flex items-center gap-2">
                    <LemonButton
                        size="small"
                        status="primary-alt"
                        noPadding
                        onClick={() => editor.chain().focus().insertContent('<ph-query />').run()}
                    >
                        Query
                    </LemonButton>

                    <LemonButton
                        size="small"
                        status="primary-alt"
                        noPadding
                        onClick={() => editor.chain().focus().insertContent('<ph-playlist />').run()}
                    >
                        Recordings
                    </LemonButton>

                    <LemonButton
                        size="small"
                        status="primary-alt"
                        noPadding
                        onClick={() => editor.chain().focus().insertContent('<ph-embed />').run()}
                    >
                        Embed
                    </LemonButton>
                </FloatingMenu>
            )} */}

            {!sourceMode ? (
                <EditorContent editor={editor} className="flex-1 overflow-y-auto" />
            ) : (
                <AutoSizer disableWidth>
                    {({ height }) => (
                        <MonacoEditor
                            theme="vs-light"
                            className="border"
                            language="html"
                            value={editor?.getHTML() ?? ''}
                            height={height}
                            loading={<Spinner />}
                            onChange={(value) => {
                                if (value) {
                                    editor?.chain().setContent(value).run()
                                }
                            }}
                        />
                    )}
                </AutoSizer>
            )}
        </div>
    )
}
