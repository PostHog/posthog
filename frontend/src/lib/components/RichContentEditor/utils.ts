import { getMarkRange } from '@tiptap/core'

import {
    EditorFocusPosition,
    EditorRange,
    JSONContent,
    RichContentEditorType,
    RichContentNode,
    RichContentNodeType,
    TTEditor,
} from './types'

export function createEditor(editor: TTEditor): RichContentEditorType {
    return {
        isEmpty: () => editor.isEmpty,
        getJSON: () => editor.getJSON(),
        getEndPosition: () => editor.state.doc.content.size,
        getSelectedNode: () => editor.state.doc.nodeAt(editor.state.selection.$anchor.pos),
        getCurrentPosition: () => editor.state.selection.$anchor.pos,
        getAdjacentNodes: (pos: number) => getAdjacentNodes(editor, pos),
        setEditable: (editable: boolean) => queueMicrotask(() => editor.setEditable(editable, false)),
        setContent: (content: JSONContent) =>
            queueMicrotask(() => editor.commands.setContent(content, { emitUpdate: false })),
        setSelection: (position: number) => editor.commands.setNodeSelection(position),
        setTextSelection: (position: number | EditorRange) =>
            queueMicrotask(() => editor.commands.setTextSelection(position)),
        focus: (position?: EditorFocusPosition) => queueMicrotask(() => editor.commands.focus(position)),
        clear: () => editor.commands.clearContent(),
        chain: () => editor.chain().focus(),
        destroy: () => editor.destroy(),
        getMarks: (type: string) => getMarks(editor, type),
        getAttributes: (typeOrName: string) => editor.getAttributes(typeOrName),
        setMark: (id: string) => editor.commands.setMark('comment', { id }),
        isActive: (name: string, attributes?: {}) => editor.isActive(name, attributes),
        isSelectionFullyWithinSingleMark: (markName: string) => {
            const markType = editor.schema.marks[markName]
            if (!markType) {
                return false
            }
            const { from, to } = editor.state.selection
            if (from >= to) {
                return false
            }
            // Use TipTap's mark range (same as extendMarkRange): walking text fragments with
            // nodesBetween is unreliable for mark views / split inline content.
            const $from = editor.state.doc.resolve(from)
            // getMarkRange defaults attrs from marks[0]; pass the mark's attrs so link+bold+comment order doesn't break.
            let markAttrs: Record<string, unknown> | undefined
            editor.state.doc.nodesBetween(from, Math.min(from + 1, to), (node) => {
                if (!node.isText) {
                    return
                }
                const instance = node.marks.find((m) => m.type === markType)
                if (instance) {
                    markAttrs = instance.attrs
                    return false
                }
            })
            const range = getMarkRange($from, markType, markAttrs)
            if (!range) {
                return false
            }
            return range.from <= from && range.to >= to
        },
        getMentions: () => getMentions(editor),
        deleteRange: (range: EditorRange) => editor.chain().focus().deleteRange(range),
        insertContent: (content: JSONContent) => editor.chain().insertContent(content).focus().run(),
        insertContentAt: (position: number, content: JSONContent) => {
            editor.chain().focus().insertContentAt(position, content).run()
            editor.commands.scrollIntoView()
        },
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
        hasChildOfType: (node: RichContentNode, type: string) => !!firstChildOfType(node, type),
        scrollToSelection: () => {
            queueMicrotask(() => {
                editor.commands.scrollIntoView()
            })
        },
        scrollToPosition(position) {
            queueMicrotask(() => {
                const { node } = editor.view.domAtPos(position)
                const element =
                    node.nodeType === Node.TEXT_NODE
                        ? (node.parentElement as HTMLElement | null)
                        : (node as HTMLElement)
                element?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
            })
        },
    }
}

export function hasChildOfType(node: RichContentNode, type: string, direct: boolean = true): boolean {
    const types: string[] = []
    node.descendants((child) => {
        types.push(child.type.name)
        return !direct
    })
    return types.includes(type)
}

export function firstChildOfType(node: RichContentNode, type: string, direct: boolean = true): RichContentNode | null {
    const children = getChildren(node, direct)
    return children.find((child) => child.type.name === type) || null
}

function findNodePositionByAttrs(editor: TTEditor, attrs: { [attr: string]: any }): number {
    return findPositionOfClosestNodeMatchingAttrs(editor, 0, attrs)
}

function findEndPositionOfNode(editor: TTEditor, position: number): number | null {
    const node = findNode(editor, position)
    return !node ? null : position + node.nodeSize
}

function findNode(editor: TTEditor, position: number): RichContentNode | null {
    return editor.state.doc.nodeAt(position)
}

function nextNode(editor: TTEditor, position: number): { node: RichContentNode; position: number } | null {
    const endPosition = findEndPositionOfNode(editor, position)
    if (!endPosition) {
        return null
    }
    const result = editor.state.doc.childAfter(endPosition)
    return result.node ? { node: result.node, position: result.offset } : null
}

function findPositionOfClosestNodeMatchingAttrs(editor: TTEditor, pos: number, attrs: { [attr: string]: any }): number {
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

function getChildren(node: RichContentNode, direct: boolean = true): RichContentNode[] {
    const children: RichContentNode[] = []
    node.descendants((child) => {
        children.push(child)
        return !direct
    })
    return children
}

function getAdjacentNodes(
    editor: TTEditor,
    pos: number
): { previous: RichContentNode | null; next: RichContentNode | null } {
    const { doc } = editor.state
    const currentIndex = doc.resolve(pos).index(0)
    return { previous: doc.maybeChild(currentIndex - 1), next: doc.maybeChild(currentIndex + 1) }
}

function getMarks(editor: TTEditor, type: string): { id: string; pos: number }[] {
    const results: { id: string; pos: number }[] = []
    const doc = editor.state.doc

    doc.descendants((node, pos) => {
        const marks = node.marks.filter((mark) => mark.type.name === type)
        marks.forEach((mark) => results.push({ id: mark.attrs.id, pos }))
    })

    return results
}

function getMentions(editor: TTEditor): number[] {
    const mentions: number[] = []

    editor.state.doc.descendants((node) => {
        if (node.type.name === RichContentNodeType.Mention) {
            mentions.push(node.attrs.id)
        }
    })

    return mentions
}
