import { lemonToast } from '@posthog/lemon-ui'
import { Editor as TTEditor } from '@tiptap/core'
import ExtensionDocument from '@tiptap/extension-document'
import { FloatingMenu } from '@tiptap/extension-floating-menu'
import ExtensionPlaceholder from '@tiptap/extension-placeholder'
import TaskItem from '@tiptap/extension-task-item'
import TaskList from '@tiptap/extension-task-list'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useActions, useMountedLogic, useValues } from 'kea'
import { sampleOne } from 'lib/utils'
import posthog from 'posthog-js'
import { useCallback, useMemo, useRef } from 'react'

import { NotebookNodeType } from '~/types'

import { NotebookMarkComment } from '../Marks/NotebookMarkComment'
import { NotebookMarkLink } from '../Marks/NotebookMarkLink'
import { NotebookNodeBacklink } from '../Nodes/NotebookNodeBacklink'
import { NotebookNodeCohort } from '../Nodes/NotebookNodeCohort'
import { NotebookNodeEarlyAccessFeature } from '../Nodes/NotebookNodeEarlyAccessFeature'
import { NotebookNodeEmbed } from '../Nodes/NotebookNodeEmbed'
import { NotebookNodeExperiment } from '../Nodes/NotebookNodeExperiment'
import { NotebookNodeFlag } from '../Nodes/NotebookNodeFlag'
import { NotebookNodeFlagCodeExample } from '../Nodes/NotebookNodeFlagCodeExample'
import { NotebookNodeGroup } from '../Nodes/NotebookNodeGroup'
import { NotebookNodeImage } from '../Nodes/NotebookNodeImage'
import { NotebookNodeLatex } from '../Nodes/NotebookNodeLatex'
import { NotebookNodeMap } from '../Nodes/NotebookNodeMap'
import { NotebookNodeMention } from '../Nodes/NotebookNodeMention'
import { NotebookNodePerson } from '../Nodes/NotebookNodePerson'
import { NotebookNodePersonFeed } from '../Nodes/NotebookNodePersonFeed/NotebookNodePersonFeed'
import { NotebookNodePlaylist } from '../Nodes/NotebookNodePlaylist'
import { NotebookNodeProperties } from '../Nodes/NotebookNodeProperties'
import { NotebookNodeQuery } from '../Nodes/NotebookNodeQuery'
import { NotebookNodeRecording } from '../Nodes/NotebookNodeRecording'
import { NotebookNodeReplayTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { NotebookNodeSurvey } from '../Nodes/NotebookNodeSurvey'
import { FloatingSuggestions } from '../Suggestions/FloatingSuggestions'
import { insertionSuggestionsLogic } from '../Suggestions/insertionSuggestionsLogic'
import { InlineMenu } from './InlineMenu'
import { MentionsExtension } from './MentionsExtension'
import { notebookLogic } from './notebookLogic'
import { SlashCommandsExtension } from './SlashCommands'
import { EditorFocusPosition, EditorRange, JSONContent, Node, textContent } from './utils'
import TableOfContents, { getHierarchicalIndexes } from '@tiptap/extension-table-of-contents'

const CustomDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

const PLACEHOLDER_TITLES = ['Release notes', 'Product roadmap', 'Meeting notes', 'Bug analysis']

export function Editor(): JSX.Element {
    const editorRef = useRef<TTEditor>()

    const mountedNotebookLogic = useMountedLogic(notebookLogic)

    const { shortId, mode } = useValues(notebookLogic)
    const { setEditor, onEditorUpdate, onEditorSelectionUpdate, setTableOfContents } = useActions(notebookLogic)

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
            TableOfContents.configure({
                getIndex: getHierarchicalIndexes,
                onUpdate(content) {
                    setTableOfContents(content)
                },
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
            }),
            TaskList,
            TaskItem.configure({
                nested: true,
            }),
            NotebookMarkLink,
            NotebookMarkComment,
            NotebookNodeLatex,
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
            NotebookNodeMention,
            NotebookNodeEmbed,
            SlashCommandsExtension,
            MentionsExtension,
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

                    if (!moved && event.dataTransfer.files && event.dataTransfer.files.length > 0) {
                        const coordinates = view.posAtCoords({
                            left: event.clientX,
                            top: event.clientY,
                        })

                        if (!coordinates) {
                            // TODO: Seek to end of document instead
                            return true
                        }

                        // if dropping external files
                        const fileList = Array.from(event.dataTransfer.files)
                        const contentToAdd: any[] = []
                        for (const file of fileList) {
                            if (file.type.startsWith('image/')) {
                                contentToAdd.push({
                                    type: NotebookNodeType.Image,
                                    attrs: { file },
                                })
                            } else {
                                lemonToast.warning('Only images can be added to Notebooks at this time.')
                            }
                        }

                        editor.chain().focus().setTextSelection(coordinates.pos).insertContent(contentToAdd).run()
                        posthog.capture('notebook files dropped', {
                            file_types: fileList.map((x) => x.type),
                        })

                        return true
                    }
                }

                return false
            },
            handlePaste: (_view, event) => {
                const editor = editorRef.current
                if (!editor) {
                    return false
                }

                // Special handling for pasting files such as images
                if (event.clipboardData && event.clipboardData.files?.length > 0) {
                    // iterate over the clipboard files and add any supported file types
                    const fileList = Array.from(event.clipboardData.files)
                    const contentToAdd: any[] = []
                    for (const file of fileList) {
                        if (file.type.startsWith('image/')) {
                            contentToAdd.push({
                                type: NotebookNodeType.Image,
                                attrs: { file },
                            })
                        } else {
                            lemonToast.warning('Only images can be added to Notebooks at this time.')
                        }
                    }

                    editor.chain().focus().insertContent(contentToAdd).run()
                    posthog.capture('notebook files pasted', {
                        file_types: fileList.map((x) => x.type),
                    })

                    return true
                }
            },
        },
        onCreate: ({ editor }) => {
            editorRef.current = editor

            // NOTE: This could be the wrong way of passing state to extensions but this is what we are using for now!
            editor.extensionStorage._notebookLogic = mountedNotebookLogic

            setEditor({
                getJSON: () => editor.getJSON(),
                getText: () => textContent(editor.state.doc),
                getEndPosition: () => editor.state.doc.content.size,
                getSelectedNode: () => editor.state.doc.nodeAt(editor.state.selection.$anchor.pos),
                getCurrentPosition: () => editor.state.selection.$anchor.pos,
                getAdjacentNodes: (pos: number) => getAdjacentNodes(editor, pos),
                setEditable: (editable: boolean) => queueMicrotask(() => editor.setEditable(editable, false)),
                setContent: (content: JSONContent) => queueMicrotask(() => editor.commands.setContent(content, false)),
                setSelection: (position: number) => editor.commands.setNodeSelection(position),
                setTextSelection: (position: number | EditorRange) => editor.commands.setTextSelection(position),
                focus: (position?: EditorFocusPosition) => queueMicrotask(() => editor.commands.focus(position)),
                chain: () => editor.chain().focus(),
                destroy: () => editor.destroy(),
                getMarks: (type: string) => getMarks(editor, type),
                findCommentPosition: (markId: string) => findCommentPosition(editor, markId),
                removeComment: (pos: number) => removeCommentMark(editor, pos),
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
            <EditorContent editor={_editor} className="NotebookEditor flex flex-col flex-1">
                {_editor && <FloatingSuggestions editor={_editor} />}
                {_editor && <InlineMenu editor={_editor} />}
            </EditorContent>
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

export function findCommentPosition(editor: TTEditor, markId: string): number | null {
    let result = null
    const doc = editor.state.doc
    doc.descendants((node, pos) => {
        const mark = node.marks.find((mark) => mark.type.name === 'comment' && mark.attrs.id === markId)
        if (mark) {
            result = pos
            return
        }
    })
    return result
}

export function getMarks(editor: TTEditor, type: string): { id: string; pos: number }[] {
    const results: { id: string; pos: number }[] = []
    const doc = editor.state.doc

    doc.descendants((node, pos) => {
        const marks = node.marks.filter((mark) => mark.type.name === type)
        marks.forEach((mark) => results.push({ id: mark.attrs.id, pos }))
    })

    return results
}

export function removeCommentMark(editor: TTEditor, pos: number): void {
    editor
        .chain()
        .setNodeSelection(pos)
        .unsetMark('comment', { extendEmptyMarkRange: true })
        .setNodeSelection(0) // need to reset the selection so that the editor does not complain after mark is removed
        .run()
}
