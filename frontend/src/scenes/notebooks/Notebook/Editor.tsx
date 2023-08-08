import posthog from 'posthog-js'
import { useActions } from 'kea'
import { useCallback, useRef } from 'react'

import { Editor as TTEditor } from '@tiptap/core'
import { useEditor, EditorContent } from '@tiptap/react'
import { FloatingMenu } from '@tiptap/extension-floating-menu'
import StarterKit from '@tiptap/starter-kit'
import ExtensionPlaceholder from '@tiptap/extension-placeholder'
import ExtensionDocument from '@tiptap/extension-document'

import { NotebookNodeFlag } from '../Nodes/NotebookNodeFlag'
import { NotebookNodeQuery } from '../Nodes/NotebookNodeQuery'
import { NotebookNodeInsight } from '../Nodes/NotebookNodeInsight'
import { NotebookNodeRecording } from '../Nodes/NotebookNodeRecording'
import { NotebookNodePlaylist } from '../Nodes/NotebookNodePlaylist'
import { NotebookNodePerson } from '../Nodes/NotebookNodePerson'
import { NotebookNodeBacklink } from '../Nodes/NotebookNodeBacklink'
import { NotebookNodeReplayTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { NotebookMarkLink } from '../Marks/NotebookMarkLink'
import { insertionSuggestionsLogic } from '../Suggestions/insertionSuggestionsLogic'
import { FloatingSuggestions } from '../Suggestions/FloatingSuggestions'
import { lemonToast } from '@posthog/lemon-ui'
import { NotebookNodeType } from '~/types'
import { NotebookNodeImage } from '../Nodes/NotebookNodeImage'

import { JSONContent, NotebookEditor, EditorFocusPosition, EditorRange, Node } from './utils'
import { SlashCommandsExtension } from './SlashCommands'
import { BacklinkCommandsExtension } from './BacklinkCommands'

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
    const logic = insertionSuggestionsLogic()
    const { resetSuggestions, setPreviousNode } = useActions(logic)

    const updatePreviousNode = useCallback(() => {
        const editor = editorRef.current
        if (editor) {
            setPreviousNode(getPreviousNode(editor))
        }
    }, [editorRef.current])

    const _editor = useEditor({
        extensions: [
            CustomDocument,
            StarterKit.configure({
                document: false,
            }),
            ExtensionPlaceholder.configure({
                placeholder: placeholder,
            }),
            FloatingMenu.extend({
                onSelectionUpdate() {
                    updatePreviousNode()
                },
                onUpdate: () => {
                    updatePreviousNode()
                    resetSuggestions()
                },
                addKeyboardShortcuts() {
                    return {
                        Tab: () => true,
                    }
                },
            }),
            NotebookMarkLink,
            NotebookNodeBacklink,
            NotebookNodeInsight,
            NotebookNodeQuery,
            NotebookNodeRecording,
            NotebookNodeReplayTimestamp,
            NotebookNodePlaylist,
            NotebookNodePerson,
            NotebookNodeFlag,
            NotebookNodeImage,
            SlashCommandsExtension,
            BacklinkCommandsExtension,
        ],
        content: initialContent,
        editorProps: {
            attributes: { class: 'NotebookEditor' },
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

                    if (!moved && event.dataTransfer.files && event.dataTransfer.files[0]) {
                        // if dropping external files
                        const file = event.dataTransfer.files[0] // the dropped file

                        posthog.capture('notebook file dropped', { file_type: file.type })

                        if (!file.type.startsWith('image/')) {
                            lemonToast.warning('Only images can be added to Notebooks at this time.')
                            return true
                        }

                        const coordinates = view.posAtCoords({
                            left: event.clientX,
                            top: event.clientY,
                        })

                        if (!coordinates) {
                            // TODO: Seek to end of document instead
                            return true
                        }

                        editor
                            .chain()
                            .focus()
                            .setTextSelection(coordinates.pos)
                            .insertContent({
                                type: NotebookNodeType.Image,
                                attrs: {
                                    file,
                                },
                            })
                            .run()

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
                setEditable: (editable: boolean) => queueMicrotask(() => editor.setEditable(editable, false)),
                setContent: (content: JSONContent) => queueMicrotask(() => editor.commands.setContent(content, false)),
                focus: (position: EditorFocusPosition) => queueMicrotask(() => editor.commands.focus(position)),
                destroy: () => editor.destroy(),
                isEmpty: () => editor.isEmpty,
                deleteRange: (range: EditorRange) => editor.chain().focus().deleteRange(range),
                insertContent: (content: JSONContent) => editor.chain().insertContent(content).focus().run(),
                insertContentAfterNode: (position: number, content: JSONContent) => {
                    const endPosition = findEndPositionOfNode(editor, position)
                    if (endPosition) {
                        editor.chain().focus().insertContentAt(endPosition, content).run()
                    }
                },
                findNode: (position: number) => findNode(editor, position),
                nextNode: (position: number) => nextNode(editor, position),
                hasChildOfType: (node: Node, type: string) => !!firstChildOfType(node, type),
            })
        },
        onUpdate: onUpdate,
    })

    return (
        <>
            <EditorContent editor={_editor} className="flex flex-col flex-1" />
            {_editor && <FloatingSuggestions editor={_editor} />}
        </>
    )
}

function findEndPositionOfNode(editor: TTEditor, position: number): number | null {
    const node = findNode(editor, position)
    return !node ? null : position + node.nodeSize
}

function findNode(editor: TTEditor, position: number): Node | null {
    return editor.state.doc.nodeAt(position)
}

function nextNode(editor: TTEditor, position: number): { node: Node; position: number } | null {
    const endPosition = findEndPositionOfNode(editor, position)
    if (!endPosition) {
        return null
    }
    const result = editor.state.doc.childAfter(endPosition)
    return result.node ? { node: result.node, position: result.offset } : null
}

export function hasChildOfType(node: Node, type: string, direct: boolean = true): boolean {
    const types: string[] = []
    node.descendants((child) => {
        types.push(child.type.name)
        return !direct
    })
    return types.includes(type)
}

export function findPositionOfClosestNodeMatchingAttrs(
    editor: TTEditor,
    pos: number,
    attrs: { [attr: string]: any }
): number {
    const matchingPositions: number[] = []
    const attrEntries = Object.entries(attrs)

    editor.state.doc.descendants((node, pos) => {
        if (attrEntries.every(([attr, value]) => node.attrs[attr] === value)) {
            matchingPositions.push(pos)
        }
    })

    return closest(matchingPositions, pos)
}

function closest(array: number[], num: number): number {
    return array.sort((a, b) => Math.abs(num - a) - Math.abs(num - b))[0]
}

export function firstChildOfType(node: Node, type: string, direct: boolean = true): Node | null {
    const children = getChildren(node, direct)
    return children.find((child) => child.type.name === type) || null
}

function getChildren(node: Node, direct: boolean = true): Node[] {
    const children: Node[] = []
    node.descendants((child) => {
        children.push(child)
        return !direct
    })
    return children
}

function getPreviousNode(editor: TTEditor): Node | null {
    const { $anchor } = editor.state.selection
    const node = $anchor.node(1)
    return !!node ? editor.state.doc.childBefore($anchor.pos - 1).node : null
}

export function hasMatchingNode(
    content: JSONContent[] | undefined,
    options: { type?: string; attrs?: { [attr: string]: any } }
): boolean {
    const attrEntries = Object.entries(options.attrs || {})
    return (
        !!content &&
        content
            .filter((node) => !options.type || node.type === options.type)
            .some((node) =>
                attrEntries.every(([attr, value]: [string, any]) => node.attrs && node.attrs[attr] === value)
            )
    )
}
