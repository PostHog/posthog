import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import ExtensionDocument from '@tiptap/extension-document'
import ExtensionPlaceholder from '@tiptap/extension-placeholder'
import { useEffect, useMemo, useRef } from 'react'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { BindLogic, useActions, useValues } from 'kea'
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
import clsx from 'clsx'
import { notebookSettingsLogic } from './notebookSettingsLogic'

export type NotebookProps = {
    shortId: string
    editable?: boolean
}

const CustomDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

const PLACEHOLDER_TITLES = ['Release notes', 'Product roadmap', 'Meeting notes', 'Bug analysis']

export function Notebook({ shortId, editable = false }: NotebookProps): JSX.Element {
    const logic = notebookLogic({ shortId })
    const { notebook, content, notebookLoading } = useValues(logic)
    const { setEditorRef, onEditorUpdate } = useActions(logic)

    const { isExpanded } = useValues(notebookSettingsLogic)

    const headingPlaceholder = useMemo(() => sampleOne(PLACEHOLDER_TITLES), [shortId])

    // Whenever our content changes, we want to ignore the next update (which is caused by the editor itself)
    const ignoreUpdateRef = useRef(true)
    useEffect(() => {
        ignoreUpdateRef.current = true
    }, [content])

    // NOTE: We shouldn't use this refernce as it can be that it is null in many of the contexts
    const _editor = useEditor({
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
        content,
        editorProps: {
            attributes: {
                class: 'NotebookEditor',
            },
            handleDrop: (view, event, _slice, moved) => {
                const editor = logic.values.editor // Only for type checking - should never be null
                if (!editor) {
                    return false
                }

                if (!moved && event.dataTransfer) {
                    const text = event.dataTransfer.getData('text/plain')
                    const node = event.dataTransfer.getData('node')
                    const properties = event.dataTransfer.getData('properties')

                    if (text.indexOf(window.location.origin) === 0 || node) {
                        // PostHog link - ensure this gets input as a proper link
                        const coordinates = view.posAtCoords({ left: event.clientX, top: event.clientY })

                        if (!coordinates) {
                            return false
                        }

                        if (node) {
                            editor
                                .chain()
                                .focus()
                                .setTextSelection(coordinates.pos)
                                .insertContent({ type: node, attrs: JSON.parse(properties) })
                                .run()
                        } else {
                            editor?.chain().focus().setTextSelection(coordinates.pos).run()
                            view.pasteText(text)
                        }

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
            if (ignoreUpdateRef.current) {
                ignoreUpdateRef.current = false
                return
            }
            onEditorUpdate()
        },
    })

    useEffect(() => {
        if (_editor) {
            setEditorRef(_editor)
        }
    }, [_editor])

    useEffect(() => {
        _editor?.setEditable(editable && !!notebook, false)
    }, [editable, _editor, notebook])

    // TODO - Render a special state if the notebook is empty

    return (
        <BindLogic logic={notebookLogic} props={{ shortId }}>
            <div className={clsx('Notebook', !isExpanded && 'Notebook--compact')}>
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
                ) : (
                    <EditorContent editor={_editor} className="flex flex-col flex-1" />
                )}
            </div>
        </BindLogic>
    )
}
