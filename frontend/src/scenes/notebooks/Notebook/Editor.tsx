import { Editor as TTEditor } from '@tiptap/core'
import { useEditor, EditorContent } from '@tiptap/react'
import { useRef } from 'react'
import StarterKit from '@tiptap/starter-kit'
import ExtensionPlaceholder from '@tiptap/extension-placeholder'
import FloatingMenu from '@tiptap/extension-floating-menu'
import ExtensionDocument from '@tiptap/extension-document'
import { EditorRange, isCurrentNodeEmpty } from './utils'

import { NotebookNodeFlag } from '../Nodes/NotebookNodeFlag'
import { NotebookNodeQuery } from 'scenes/notebooks/Nodes/NotebookNodeQuery'
import { NotebookNodeInsight } from 'scenes/notebooks/Nodes/NotebookNodeInsight'
import { NotebookNodeRecording } from 'scenes/notebooks/Nodes/NotebookNodeRecording'
import { NotebookNodePlaylist } from 'scenes/notebooks/Nodes/NotebookNodePlaylist'
import { NotebookNodePerson } from '../Nodes/NotebookNodePerson'
import { NotebookNodeLink } from '../Nodes/NotebookNodeLink'

import posthog from 'posthog-js'
import { FloatingSlashCommands, SlashCommandsExtension } from './SlashCommands'
import { JSONContent, NotebookEditor } from './utils'

const CustomDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

export function Editor({
    initialContent,
    onCreate,
    onUpdate,
    placeholder,
}: {
    initialContent: JSONContent
    onCreate: (editor: NotebookEditor) => void
    onUpdate: () => void
    placeholder: ({ node }: { node: any }) => string
}): JSX.Element {
    const editorRef = useRef<TTEditor>()

    const _editor = useEditor({
        extensions: [
            CustomDocument,
            StarterKit.configure({
                document: false,
            }),
            ExtensionPlaceholder.configure({
                placeholder: placeholder,
            }),
            FloatingMenu.configure({
                shouldShow: ({ editor }) => {
                    console.log('Floating extension')
                    if (!editor) {
                        return false
                    }
                    if (
                        editor.view.hasFocus() &&
                        editor.isEditable &&
                        editor.isActive('paragraph') &&
                        isCurrentNodeEmpty(editor)
                    ) {
                        return true
                    }

                    return false
                },
            }),
            NotebookNodeLink,

            NotebookNodeInsight,
            NotebookNodeQuery,
            NotebookNodeRecording,
            NotebookNodePlaylist,
            NotebookNodePerson,
            NotebookNodeFlag,
            SlashCommandsExtension,
        ],
        content: initialContent,
        editorProps: {
            attributes: {
                class: 'NotebookEditor',
            },
            handleDrop: (view, event, _slice, moved) => {
                const editor = editorRef.current
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

                            // We report this case, the pasted version is handled by the posthogNodePasteRule
                            posthog.capture('notebook node dropped', { node_type: node })
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
        onCreate: ({ editor }) => {
            editorRef.current = editor
            onCreate({
                getJSON: () => editor.getJSON(),
                setEditable: (editable: boolean) => editor.setEditable(editable, false),
                setContent: (content: JSONContent) => editor.commands.setContent(content, false),
                isEmpty: () => editor.isEmpty,
                deleteRange: (range: EditorRange) => editor.chain().focus().deleteRange(range),
            })
        },
        onUpdate: onUpdate,
        onDestroy: () => {},
    })

    return (
        <>
            <EditorContent editor={_editor} className="flex flex-col flex-1" />
            {_editor && <FloatingSlashCommands editor={_editor} />}
        </>
    )
}
