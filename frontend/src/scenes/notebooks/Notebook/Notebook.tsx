import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useEffect } from 'react'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { useActions, useValues } from 'kea'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import MonacoEditor from '@monaco-editor/react'
import { Spinner } from 'lib/lemon-ui/Spinner'
import './Notebook.scss'

import { NotebookNodeFlag } from '../Nodes/NotebookNodeFlag'
import { NotebookNodeQuery } from 'scenes/notebooks/Nodes/NotebookNodeQuery'
import { NotebookNodeInsight } from 'scenes/notebooks/Nodes/NotebookNodeInsight'
import { NotebookNodeRecording } from 'scenes/notebooks/Nodes/NotebookNodeRecording'
import { NotebookNodePlaylist } from 'scenes/notebooks/Nodes/NotebookNodePlaylist'
import { NotebookNodePerson } from '../Nodes/NotebookNodePerson'

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
        extensions: [
            StarterKit,
            NotebookNodeInsight,
            NotebookNodeQuery,
            NotebookNodeRecording,
            NotebookNodePlaylist,
            NotebookNodePerson,
            NotebookNodeFlag,
        ],
        content,
        editorProps: {
            attributes: {
                class: 'Notebook',
            },
            handleDrop: (view, event, slice, moved) => {

                if (!moved && event.dataTransfer) {
                    const text = event.dataTransfer.getData('text/plain')

                    if (text.indexOf(window.location.origin) === 0) {
                        // PostHog link - ensure this gets input as a proper link
                        const coordinates = view.posAtCoords({ left: event.clientX, top: event.clientY })

                        if (!coordinates) {
                            return false
                        }

                        editor?.chain().focus().setTextSelection(coordinates.pos).run()
                        view.pasteText(text)

                        return true
                    }

                    if (event.dataTransfer.files && event.dataTransfer.files[0]) {
                        // if dropping external files
                        const file = event.dataTransfer.files[0] // the dropped file

                        console.log('TODO: Dropped file!', file)
                        // TODO: Detect if it is an image and add image upload handler

                        return true
                    }
                }

                return false
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
