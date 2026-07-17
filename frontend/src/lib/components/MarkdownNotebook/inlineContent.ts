import { FloatingToolbarTextRange } from './editorTypes'
import { NotebookInlineMark, NotebookInlineNode, NotebookTextSelectionRange } from './types'
import { getInlineText, normalizeInlineNodes } from './utils'

export function plainTextToInlineNodes(text: string): NotebookInlineNode[] {
    if (!text) {
        return []
    }

    const nodes: NotebookInlineNode[] = []
    text.split('\n').forEach((line, index) => {
        if (index > 0) {
            nodes.push({ type: 'hardBreak' })
        }
        if (line) {
            nodes.push({ type: 'text', text: line })
        }
    })

    return normalizeInlineNodes(nodes)
}

export function getSelectedLinkHref(nodes: NotebookInlineNode[], range: NotebookTextSelectionRange): string | null {
    const selectedChildren = getInlineNodesInRange(nodes, range)
    const linkedTextNode = selectedChildren.find(
        (node) => node.type === 'text' && (node.marks ?? []).some((mark) => mark.type === 'link')
    )

    if (!linkedTextNode || linkedTextNode.type === 'hardBreak') {
        return null
    }

    return linkedTextNode.marks?.find((mark) => mark.type === 'link')?.href ?? null
}

export function getInlineNodesInRange(
    nodes: NotebookInlineNode[],
    range: NotebookTextSelectionRange
): NotebookInlineNode[] {
    const textLength = getInlineText(nodes).length
    const selectionStart = Math.max(0, Math.min(Math.min(range.start, range.end), textLength))
    const selectionEnd = Math.max(selectionStart, Math.min(Math.max(range.start, range.end), textLength))
    const [, selectionAndAfter] = splitInlineNodesAt(nodes, selectionStart)
    const [selectedChildren] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)

    return selectedChildren
}

export function applyLinkMarkToInlineNodes(nodes: NotebookInlineNode[], href: string): NotebookInlineNode[] {
    return nodes.map((node) => {
        if (node.type === 'hardBreak') {
            return node
        }

        const marks: NotebookInlineMark[] = [
            ...(node.marks ?? []).filter((mark) => mark.type !== 'link'),
            { type: 'link', href },
        ]
        return { ...node, marks }
    })
}

export function setInlineMark(
    nodes: NotebookInlineNode[],
    range: NotebookTextSelectionRange,
    markType: NotebookInlineMark['type'],
    shouldApplyMark: boolean
): NotebookInlineNode[] {
    const normalizedStart = Math.min(range.start, range.end)
    const normalizedEnd = Math.max(range.start, range.end)
    let offset = 0
    const output: NotebookInlineNode[] = []

    nodes.forEach((node) => {
        const length = node.type === 'hardBreak' ? 1 : node.text.length
        const nodeStart = offset
        const nodeEnd = offset + length
        offset = nodeEnd

        if (node.type === 'hardBreak' || nodeEnd <= normalizedStart || nodeStart >= normalizedEnd) {
            output.push(node)
            return
        }

        const selectionStart = Math.max(normalizedStart - nodeStart, 0)
        const selectionEnd = Math.min(normalizedEnd - nodeStart, node.text.length)

        if (selectionStart > 0) {
            output.push({ ...node, text: node.text.slice(0, selectionStart) })
        }

        output.push({
            ...node,
            text: node.text.slice(selectionStart, selectionEnd),
            marks: setMark(node.marks ?? [], markType, shouldApplyMark),
        })

        if (selectionEnd < node.text.length) {
            output.push({ ...node, text: node.text.slice(selectionEnd) })
        }
    })

    return normalizeInlineNodes(output)
}

export type InlineMarkSelection = {
    children: NotebookInlineNode[]
    range: NotebookTextSelectionRange
}

export function areInlineSelectionsFullyMarked(
    selections: InlineMarkSelection[],
    markType: NotebookInlineMark['type']
): boolean {
    let hasSelectedText = false

    for (const { children, range } of selections) {
        const rangeHasText = doesInlineRangeContainText(children, range)
        if (!rangeHasText) {
            continue
        }

        hasSelectedText = true
        if (!isInlineRangeFullyMarked(children, range, markType)) {
            return false
        }
    }

    return hasSelectedText
}

export function areSelectedTextRangesFullyMarked(
    textRanges: FloatingToolbarTextRange[],
    markType: NotebookInlineMark['type']
): boolean {
    return areInlineSelectionsFullyMarked(
        textRanges.map(({ node, range }) => ({ children: node.children, range })),
        markType
    )
}

export function doesInlineRangeContainText(nodes: NotebookInlineNode[], range: NotebookTextSelectionRange): boolean {
    const normalizedStart = Math.min(range.start, range.end)
    const normalizedEnd = Math.max(range.start, range.end)
    let offset = 0

    return nodes.some((node) => {
        const length = node.type === 'hardBreak' ? 1 : node.text.length
        const nodeStart = offset
        const nodeEnd = offset + length
        offset = nodeEnd

        return node.type !== 'hardBreak' && Math.max(normalizedStart, nodeStart) < Math.min(normalizedEnd, nodeEnd)
    })
}

export function isInlineRangeFullyMarked(
    nodes: NotebookInlineNode[],
    range: NotebookTextSelectionRange,
    markType: NotebookInlineMark['type']
): boolean {
    const normalizedStart = Math.min(range.start, range.end)
    const normalizedEnd = Math.max(range.start, range.end)
    let offset = 0

    return nodes.every((node) => {
        const length = node.type === 'hardBreak' ? 1 : node.text.length
        const nodeStart = offset
        const nodeEnd = offset + length
        offset = nodeEnd

        if (node.type === 'hardBreak' || Math.max(normalizedStart, nodeStart) >= Math.min(normalizedEnd, nodeEnd)) {
            return true
        }

        return node.marks?.some((mark) => mark.type === markType) ?? false
    })
}

export function setInlineLinkMark(
    nodes: NotebookInlineNode[],
    range: NotebookTextSelectionRange,
    href: string | null
): NotebookInlineNode[] {
    const normalizedStart = Math.min(range.start, range.end)
    const normalizedEnd = Math.max(range.start, range.end)
    let offset = 0
    const output: NotebookInlineNode[] = []

    nodes.forEach((node) => {
        const length = node.type === 'hardBreak' ? 1 : node.text.length
        const nodeStart = offset
        const nodeEnd = offset + length
        offset = nodeEnd

        if (node.type === 'hardBreak' || nodeEnd <= normalizedStart || nodeStart >= normalizedEnd) {
            output.push(node)
            return
        }

        const selectionStart = Math.max(normalizedStart - nodeStart, 0)
        const selectionEnd = Math.min(normalizedEnd - nodeStart, node.text.length)

        if (selectionStart > 0) {
            output.push({ ...node, text: node.text.slice(0, selectionStart) })
        }

        output.push({
            ...node,
            text: node.text.slice(selectionStart, selectionEnd),
            marks: setLinkMark(node.marks ?? [], href),
        })

        if (selectionEnd < node.text.length) {
            output.push({ ...node, text: node.text.slice(selectionEnd) })
        }
    })

    return normalizeInlineNodes(output)
}

export function setMark(
    marks: NotebookInlineMark[],
    markType: NotebookInlineMark['type'],
    shouldApplyMark: boolean
): NotebookInlineMark[] | undefined {
    // Marks that carry an identity (link href, ref/mention ids) cannot be toggled generically.
    if (markType === 'link' || markType === 'ref' || markType === 'mention') {
        return marks.length ? marks : undefined
    }

    const existing = marks.some((mark) => mark.type === markType)
    if (shouldApplyMark) {
        return existing ? marks : [...marks, { type: markType }]
    }

    const nextMarks = marks.filter((mark) => mark.type !== markType)

    return nextMarks.length ? nextMarks : undefined
}

export function setLinkMark(marks: NotebookInlineMark[], href: string | null): NotebookInlineMark[] | undefined {
    const marksWithoutLink = marks.filter((mark) => mark.type !== 'link')
    const nextMarks = href ? [...marksWithoutLink, { type: 'link' as const, href }] : marksWithoutLink

    return nextMarks.length ? nextMarks : undefined
}

/** Wraps the selected range in a ref mark (`<ref id="…">`), anchoring an inline AI prompt to it. */
export function setInlineRefMark(
    nodes: NotebookInlineNode[],
    range: NotebookTextSelectionRange,
    refId: string
): NotebookInlineNode[] {
    const normalizedStart = Math.min(range.start, range.end)
    const normalizedEnd = Math.max(range.start, range.end)
    let offset = 0
    const output: NotebookInlineNode[] = []

    nodes.forEach((node) => {
        const length = node.type === 'hardBreak' ? 1 : node.text.length
        const nodeStart = offset
        const nodeEnd = offset + length
        offset = nodeEnd

        if (node.type === 'hardBreak' || nodeEnd <= normalizedStart || nodeStart >= normalizedEnd) {
            output.push(node)
            return
        }

        const selectionStart = Math.max(normalizedStart - nodeStart, 0)
        const selectionEnd = Math.min(normalizedEnd - nodeStart, node.text.length)

        if (selectionStart > 0) {
            output.push({ ...node, text: node.text.slice(0, selectionStart) })
        }

        output.push({
            ...node,
            text: node.text.slice(selectionStart, selectionEnd),
            marks: [...(node.marks ?? []).filter((mark) => mark.type !== 'ref'), { type: 'ref', id: refId }],
        })

        if (selectionEnd < node.text.length) {
            output.push({ ...node, text: node.text.slice(selectionEnd) })
        }
    })

    return normalizeInlineNodes(output)
}

/** Removes ref marks with the given id, keeping the text when the paired prompt is deleted. */
export function removeInlineRefMark(nodes: NotebookInlineNode[], refId: string): NotebookInlineNode[] {
    let didChange = false
    const output = nodes.map((node) => {
        if (node.type === 'hardBreak') {
            return node
        }
        const marks = node.marks ?? []
        const nextMarks = marks.filter((mark) => !(mark.type === 'ref' && mark.id === refId))
        if (nextMarks.length === marks.length) {
            return node
        }
        didChange = true
        return { ...node, marks: nextMarks.length ? nextMarks : undefined }
    })

    return didChange ? normalizeInlineNodes(output) : nodes
}

export function splitInlineNodesAt(
    nodes: NotebookInlineNode[],
    offset: number
): [NotebookInlineNode[], NotebookInlineNode[]] {
    const before: NotebookInlineNode[] = []
    const after: NotebookInlineNode[] = []
    let currentOffset = 0

    nodes.forEach((node) => {
        const length = node.type === 'hardBreak' ? 1 : node.text.length
        if (currentOffset + length <= offset) {
            before.push(node)
            currentOffset += length
            return
        }
        if (currentOffset >= offset) {
            after.push(node)
            currentOffset += length
            return
        }
        if (node.type === 'hardBreak') {
            after.push(node)
            currentOffset += length
            return
        }

        const splitOffset = offset - currentOffset
        before.push({ ...node, text: node.text.slice(0, splitOffset) })
        after.push({ ...node, text: node.text.slice(splitOffset) })
        currentOffset += length
    })

    return [normalizeInlineNodes(before), normalizeInlineNodes(after)]
}
