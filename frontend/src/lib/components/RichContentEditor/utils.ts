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
        getJSON: () => editor.getJSON(),
        getEndPosition: () => editor.state.doc.content.size,
        getSelectedNode: () => editor.state.doc.nodeAt(editor.state.selection.$anchor.pos),
        getCurrentPosition: () => editor.state.selection.$anchor.pos,
        getAdjacentNodes: (pos: number) => getAdjacentNodes(editor, pos),
        setEditable: (editable: boolean) => queueMicrotask(() => editor.setEditable(editable, false)),
        setContent: (content: JSONContent) =>
            queueMicrotask(() => editor.commands.setContent(content, { emitUpdate: false })),
        setSelection: (position: number) => editor.commands.setNodeSelection(position),
        setTextSelection: (position: number | EditorRange) => editor.commands.setTextSelection(position),
        focus: (position?: EditorFocusPosition) => queueMicrotask(() => editor.commands.focus(position)),
        clear: () => editor.commands.clearContent(),
        chain: () => editor.chain().focus(),
        destroy: () => editor.destroy(),
        getMarks: (type: string) => getMarks(editor, type),
        setMark: (id: string) => editor.commands.setMark('comment', { id }),
        isActive: (name: string, attributes?: {}) => editor.isActive(name, attributes),
        getMentions: () => getMentions(editor),
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
        hasChildOfType: (node: RichContentNode, type: string) => !!firstChildOfType(node, type),
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
