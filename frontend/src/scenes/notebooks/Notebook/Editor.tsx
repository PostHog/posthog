import posthog from 'posthog-js'
import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { Editor as TTEditor } from '@tiptap/core'
import { EditorContent, useEditor } from '@tiptap/react'
import { FloatingMenu } from '@tiptap/extension-floating-menu'
import StarterKit from '@tiptap/starter-kit'
import ExtensionPlaceholder from '@tiptap/extension-placeholder'
import ExtensionDocument from '@tiptap/extension-document'
import TaskItem from '@tiptap/extension-task-item'
import TaskList from '@tiptap/extension-task-list'

import { NotebookNodeFlagCodeExample } from '../Nodes/NotebookNodeFlagCodeExample'
import { NotebookNodeFlag } from '../Nodes/NotebookNodeFlag'
import { NotebookNodeExperiment } from '../Nodes/NotebookNodeExperiment'
import { NotebookNodeQuery } from '../Nodes/NotebookNodeQuery'
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

import { EditorFocusPosition, EditorRange, JSONContent, Node, textContent } from './utils'
import { SlashCommandsExtension } from './SlashCommands'
import { BacklinkCommandsExtension } from './BacklinkCommands'
import { NotebookNodeEarlyAccessFeature } from '../Nodes/NotebookNodeEarlyAccessFeature'
import { NotebookNodeSurvey } from '../Nodes/NotebookNodeSurvey'
import { InlineMenu } from './InlineMenu'
import NodeGapInsertionExtension from './Extensions/NodeGapInsertion'
import { notebookLogic } from './notebookLogic'
import { sampleOne } from 'lib/utils'
import { NotebookNodeGroup } from '../Nodes/NotebookNodeGroup'
import { NotebookNodeCohort } from '../Nodes/NotebookNodeCohort'
import { NotebookNodePersonFeed } from '../Nodes/NotebookNodePersonFeed/NotebookNodePersonFeed'
import { NotebookNodeProperties } from '../Nodes/NotebookNodeProperties'
import { NotebookNodeMap } from '../Nodes/NotebookNodeMap'

const CustomDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

const PLACEHOLDER_TITLES = ['Release notes', 'Product roadmap', 'Meeting notes', 'Bug analysis']

export function Editor(): JSX.Element {
    const editorRef = useRef<TTEditor>()

    const { shortId, mode } = useValues(notebookLogic)
    const { setEditor, onEditorUpdate, onEditorSelectionUpdate } = useActions(notebookLogic)

    const { resetSuggestions, setPreviousNode } = useActions(insertionSuggestionsLogic)

    const headingPlaceholder = useMemo(() => sampleOne(PLACEHOLDER_TITLES), [shortId])

    const updatePreviousNode = useCallback(() => {
        const editor = editorRef.current
        if (editor) {
            setPreviousNode(getNodeBeforeActiveNode(editor))
        }
    }, [editorRef.current])

    const _editor = useEditor({
        extensions: [
            mode === 'notebook' ? CustomDocument : ExtensionDocument,
            StarterKit.configure({
                document: false,
                gapcursor: false,
            }),
            ExtensionPlaceholder.configure({
                placeholder: ({ node }: { node: any }) => {
                    if (node.type.name === 'heading' && node.attrs.level === 1) {
                        return `Untitled - maybe.. "${headingPlaceholder}"`
                    }

                    if (node.type.name === 'heading') {
                        return `Heading ${node.attrs.level}`
                    }

                    return ''
                },
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
            TaskList,
            TaskItem.configure({
                nested: true,
            }),
            NotebookMarkLink,
            NotebookNodeBacklink,
            NotebookNodeQuery,
            NotebookNodeRecording,
            NotebookNodeReplayTimestamp,
            NotebookNodePlaylist,
            NotebookNodePerson,
            NotebookNodeCohort,
            NotebookNodeGroup,
            NotebookNodeFlagCodeExample,
            NotebookNodeFlag,
            NotebookNodeExperiment,
            NotebookNodeEarlyAccessFeature,
            NotebookNodeSurvey,
            NotebookNodeImage,
            NotebookNodeProperties,
            SlashCommandsExtension,
            BacklinkCommandsExtension,
            NodeGapInsertionExtension,
            NotebookNodePersonFeed,
            NotebookNodeMap,
        ],
        editorProps: {
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

            setEditor({
                getJSON: () => editor.getJSON(),
                getText: () => textContent(editor.state.doc),
                getEndPosition: () => editor.state.doc.content.size,
                getSelectedNode: () => editor.state.doc.nodeAt(editor.state.selection.$anchor.pos),
                getAdjacentNodes: (pos: number) => getAdjacentNodes(editor, pos),
                setEditable: (editable: boolean) => queueMicrotask(() => editor.setEditable(editable, false)),
                setContent: (content: JSONContent) => queueMicrotask(() => editor.commands.setContent(content, false)),
                setSelection: (position: number) => editor.commands.setNodeSelection(position),
                setTextSelection: (position: number | EditorRange) => editor.commands.setTextSelection(position),
                focus: (position: EditorFocusPosition) => queueMicrotask(() => editor.commands.focus(position)),
                destroy: () => editor.destroy(),
                deleteRange: (range: EditorRange) => editor.chain().focus().deleteRange(range),
                insertContent: (content: JSONContent) => editor.chain().insertContent(content).focus().run(),
                insertContentAfterNode: (position: number, content: JSONContent) => {
                    const endPosition = findEndPositionOfNode(editor, position)
                    if (endPosition) {
                        editor.chain().focus().insertContentAt(endPosition, content).run()
                        editor.commands.scrollIntoView()
                    }
                },
                pasteContent: (position: number, text: string) => {
                    editor?.chain().focus().setTextSelection(position).run()
                    editor?.view.pasteText(text)
                },
                findNode: (position: number) => findNode(editor, position),
                findNodePositionByAttrs: (attrs: Record<string, any>) => findNodePositionByAttrs(editor, attrs),
                nextNode: (position: number) => nextNode(editor, position),
                hasChildOfType: (node: Node, type: string) => !!firstChildOfType(node, type),
                scrollToSelection: () => {
                    queueMicrotask(() => {
                        const position = editor.state.selection.$anchor.pos
                        const domEl = editor.view.nodeDOM(position) as HTMLElement
                        domEl.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' })
                    })
                },
                scrollToPosition(position) {
                    queueMicrotask(() => {
                        const domEl = editor.view.nodeDOM(position) as HTMLElement
                        domEl.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' })
                    })
                },
            })
        },
        onUpdate: onEditorUpdate,
        onSelectionUpdate: onEditorSelectionUpdate,
    })

    return (
        <>
            <EditorContent editor={_editor} className="NotebookEditor flex flex-col flex-1" />
            {_editor && <FloatingSuggestions editor={_editor} />}
            {_editor && <InlineMenu editor={_editor} />}
        </>
    )
}

function findNodePositionByAttrs(editor: TTEditor, attrs: { [attr: string]: any }): number {
    return findPositionOfClosestNodeMatchingAttrs(editor, 0, attrs)
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

function getAdjacentNodes(editor: TTEditor, pos: number): { previous: Node | null; next: Node | null } {
    const { doc } = editor.state
    const currentIndex = doc.resolve(pos).index(0)
    return { previous: doc.maybeChild(currentIndex - 1), next: doc.maybeChild(currentIndex + 1) }
}

function getNodeBeforeActiveNode(editor: TTEditor): Node | null {
    const { doc, selection } = editor.state
    const currentIndex = doc.resolve(selection.$anchor.pos).index(0)
    return doc.maybeChild(currentIndex - 1)
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
