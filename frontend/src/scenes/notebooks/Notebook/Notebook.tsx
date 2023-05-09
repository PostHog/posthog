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
            NotebookNodeFlag,
        ],
        content,
        editorProps: {
            attributes: {
                class: 'Notebook',
            },
            handleDrop: (view, event, slice, moved) => {
                console.log(view, event, slice, moved)

                if (event.dataTransfer?.getData('node')) {
                    const nodeType = event.dataTransfer.getData('node')
                    const properties = JSON.parse(event.dataTransfer.getData('properties'))

                    const { schema } = view.state
                    const coordinates = view.posAtCoords({ left: event.clientX, top: event.clientY })
                    if (!coordinates) {
                        return false
                    }
                    const node = schema.nodes[nodeType].create(properties)
                    const transaction = view.state.tr.insert(coordinates.pos, node) // places it in the correct position
                    return view.dispatch(transaction)
                }
                if (!moved && event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0]) {
                    // if dropping external files
                    const file = event.dataTransfer.files[0] // the dropped file

                    console.log('FILE!', file)
                    // TODO: Add image with upload handler

                    return true // handled
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
