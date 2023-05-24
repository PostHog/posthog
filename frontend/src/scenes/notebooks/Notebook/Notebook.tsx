import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import ExtensionDocument from '@tiptap/extension-document'
import ExtensionPlaceholder from '@tiptap/extension-placeholder'
import { useEffect, useMemo } from 'react'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { BindLogic, useActions, useValues } from 'kea'
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
import { NotebookNodeLink } from '../Nodes/NotebookNodeLink'
import { sampleOne } from 'lib/utils'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { NotFound } from 'lib/components/NotFound'

export type NotebookProps = {
    shortId: string
    sourceMode?: boolean
    editable?: boolean
}

const CustomDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

const PLACEHOLDER_TITLES = ['Release notes', 'Product roadmap', 'Meeting notes', 'Bug analysis']

export function Notebook({ shortId, sourceMode, editable = false }: NotebookProps): JSX.Element {
    const logic = notebookLogic({ shortId })
    const { notebook, content, notebookLoading } = useValues(logic)
    const { setEditorRef, onEditorUpdate } = useActions(logic)

    const headingPlaceholder = useMemo(() => sampleOne(PLACEHOLDER_TITLES), [shortId])

    const editor = useEditor({
        extensions: [
            CustomDocument,
            StarterKit.configure({
                document: false,
            }),
            ExtensionPlaceholder.configure({
                placeholder: ({ node }) => {
                    if (node.type.name === 'heading' && node.attrs.level === 1) {
                        return `Untitled - maybe.. "${headingPlaceholder}"`
                    }

                    if (node.type.name === 'heading') {
                        return `Heading ${node.attrs.level}`
                    }

                    return ''
                },
            }),
            NotebookNodeLink,

            NotebookNodeInsight,
            NotebookNodeQuery,
            NotebookNodeRecording,
            NotebookNodePlaylist,
            NotebookNodePerson,
            NotebookNodeFlag,

            // Ensure this is last as a fallback for all PostHog links
            // LinkExtension.configure({}),
        ],
        // This is only the default content. It is not reactive
        content,
        editorProps: {
            attributes: {
                class: 'NotebookEditor',
            },
            handleDrop: (view, event, _slice, moved) => {
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
        onUpdate: ({}) => {
            onEditorUpdate()
        },
    })

    useEffect(() => {
        if (editor) {
            setEditorRef(editor)
        }
    }, [editor])

    useEffect(() => {
        editor?.setEditable(editable && !!notebook)
    }, [editable, editor, notebook])

    // TODO - Render a special state if the notebook is empty

    return (
        <BindLogic logic={notebookLogic} props={{ shortId }}>
            <div className="Notebook">
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

                {!notebook && notebookLoading ? (
                    <div className="space-y-4 px-8 py-4">
                        <LemonSkeleton className="w-1/2 h-8" />
                        <LemonSkeleton className="w-1/3 h-4" />
                        <LemonSkeleton className="h-4" />
                        <LemonSkeleton className="h-4" />
                    </div>
                ) : !notebook ? (
                    <NotFound object={'recording'} />
                ) : !sourceMode ? (
                    <EditorContent editor={editor} className="flex flex-col flex-1 overflow-y-auto" />
                ) : (
                    <AutoSizer disableWidth>
                        {({ height }) => (
                            <MonacoEditor
                                theme="vs-light"
                                language="json"
                                value={JSON.stringify(editor?.getJSON(), null, 2) ?? ''}
                                height={height}
                                loading={<Spinner />}
                                onChange={(value) => {
                                    if (value) {
                                        try {
                                            editor?.chain().setContent(JSON.parse(value)).run()
                                        } catch (e) {
                                            console.error(e)
                                        }
                                    }
                                }}
                            />
                        )}
                    </AutoSizer>
                )}
            </div>
        </BindLogic>
    )
}
