import { isTextBlockNode, serializeNotebookNodes } from './documentModel'
import {
    FloatingToolbarCodeRange,
    FloatingToolbarListItemRange,
    FloatingToolbarTextRange,
    InlineLinkPasteResult,
    NOTEBOOK_EDITABLE_BLOCK_SELECTOR,
    RestoreSelectionRequest,
    RestoreTextRange,
} from './editorTypes'
import { applyLinkMarkToInlineNodes, splitInlineNodesAt } from './inlineContent'
import { getListItemRefKey } from './listModel'
import { sanitizeNotebookLinkHref } from './markdown'
import {
    NotebookBlockNode,
    NotebookComponentBlockNode,
    NotebookInlineNode,
    NotebookListBlockNode,
    NotebookTextBlockNode,
    NotebookTextSelectionRange,
} from './types'
import { getInlineText, normalizeInlineNodes } from './utils'

export function getNotebookBlockElement(rootElement: HTMLElement | null, nodeId: string): HTMLElement | null {
    return (
        rootElement?.querySelector<HTMLElement>(
            `[data-markdown-notebook-node-id="${escapeAttributeSelectorValue(nodeId)}"]`
        ) ?? null
    )
}

export function escapeAttributeSelectorValue(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

export function getElementLineHeight(element: HTMLElement): number {
    const styles = window.getComputedStyle(element)
    const lineHeight = Number.parseFloat(styles.lineHeight)
    if (Number.isFinite(lineHeight)) {
        return lineHeight
    }

    const fontSize = Number.parseFloat(styles.fontSize)
    return Number.isFinite(fontSize) ? fontSize * 1.55 : 24
}

export function getSelectionRange(element: HTMLElement, nodeId: string): NotebookTextSelectionRange | null {
    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0) {
        return null
    }

    const range = selection.getRangeAt(0)
    if (!element.contains(range.commonAncestorContainer) && !rangeIntersectsNode(range, element)) {
        return null
    }
    const textLength = element.textContent?.length ?? 0

    return {
        nodeId,
        start: element.contains(range.startContainer)
            ? getTextOffset(element, range.startContainer, range.startOffset)
            : 0,
        end: element.contains(range.endContainer)
            ? getTextOffset(element, range.endContainer, range.endOffset)
            : textLength,
    }
}

export function getNormalizedSelectionBounds(
    node: NotebookTextBlockNode,
    element: HTMLElement
): { start: number; end: number; textLength: number } {
    const textLength = getInlineText(node.children).length
    const range = getSelectionRange(element, node.id)
    if (!range) {
        return { start: 0, end: textLength, textLength }
    }

    const start = Math.max(0, Math.min(Math.min(range.start, range.end), textLength))
    const end = Math.max(start, Math.min(Math.max(range.start, range.end), textLength))
    return { start, end, textLength }
}

export function getSelectionClientRect(range: Range): DOMRect | null {
    if (typeof range.getBoundingClientRect !== 'function') {
        return null
    }

    const rect = range.getBoundingClientRect()
    if (rect.width || rect.height) {
        return rect
    }

    return typeof range.getClientRects === 'function' ? (range.getClientRects()[0] ?? null) : null
}

export function getCollapsedSelectionRange(element: HTMLElement, nodeId: string): NotebookTextSelectionRange | null {
    const range = getSelectionRange(element, nodeId)
    if (!range) {
        return null
    }
    return { nodeId, start: range.end, end: range.end }
}

export function getTextOffset(root: HTMLElement, container: Node, offset: number): number {
    const range = document.createRange()
    range.selectNodeContents(root)
    range.setEnd(container, offset)
    return range.toString().length
}

export function restoreSelection(element: HTMLElement, start: number, end: number): void {
    if (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement) {
        element.focus()
        element.setSelectionRange(start, end)
        return
    }

    const selection = window.getSelection()
    if (!selection) {
        return
    }

    const range = document.createRange()
    const startPosition = findTextPosition(element, start)
    const endPosition = findTextPosition(element, end)
    range.setStart(startPosition.node, startPosition.offset)
    range.setEnd(endPosition.node, endPosition.offset)
    selection.removeAllRanges()
    selection.addRange(range)
}

export function scrollNotebookElementIntoView(element: HTMLElement): void {
    if (typeof element.scrollIntoView !== 'function') {
        return
    }

    element.scrollIntoView({ block: 'nearest', inline: 'nearest' })
}

export function setNotebookSelectionStart(range: Range, node: NotebookBlockNode, element: HTMLElement): void {
    if (isTextBlockNode(node)) {
        const startPosition = findTextPosition(element, 0)
        range.setStart(startPosition.node, startPosition.offset)
        return
    }

    range.setStartBefore(element)
}

export function setNotebookSelectionEnd(range: Range, node: NotebookBlockNode, element: HTMLElement): void {
    if (isTextBlockNode(node)) {
        const endPosition = findTextPosition(element, getInlineText(node.children).length)
        range.setEnd(endPosition.node, endPosition.offset)
        return
    }

    range.setEndAfter(element)
}

export function restoreTextSelectionRanges(
    ranges: RestoreTextRange[],
    blockRefs: Record<string, HTMLElement | null>,
    listItemRefs: Record<string, HTMLElement | null> = {}
): void {
    const firstRange = ranges[0]
    const lastRange = ranges[ranges.length - 1]
    if (!firstRange || !lastRange) {
        return
    }

    const resolveElement = (range: RestoreTextRange): HTMLElement | null =>
        range.listItemIndex === undefined
            ? (blockRefs[range.nodeId] ?? null)
            : (listItemRefs[getListItemRefKey(range.nodeId, range.listItemIndex)] ?? null)
    const firstElement = resolveElement(firstRange)
    const lastElement = resolveElement(lastRange)
    const selection = window.getSelection()
    if (!firstElement || !lastElement || !selection) {
        return
    }

    const range = document.createRange()
    const startPosition = findTextPosition(firstElement, Math.min(firstRange.start, firstRange.end))
    const endPosition = findTextPosition(lastElement, Math.max(lastRange.start, lastRange.end))
    range.setStart(startPosition.node, startPosition.offset)
    range.setEnd(endPosition.node, endPosition.offset)
    selection.removeAllRanges()
    selection.addRange(range)
}

export function getElementForNode(node: Node): Element | null {
    return node instanceof Element ? node : node.parentElement
}

export function getClosestEditableBlockElement(element: Element | null): HTMLElement | null {
    const editableElement = element?.closest(NOTEBOOK_EDITABLE_BLOCK_SELECTOR)
    return editableElement instanceof HTMLElement ? editableElement : null
}

export function getSelectedInlineEditableElementOfType(
    notebookElement: HTMLElement | null,
    className: string
): HTMLElement | null {
    if (!notebookElement) {
        return null
    }

    const element = getInlineEditableElementForSelection(window.getSelection(), notebookElement)
    return element?.classList.contains(className) ? element : null
}

export function getInlineEditableElementForSelection(
    selection: Selection | null,
    rootElement: HTMLElement
): HTMLElement | null {
    if (!selection?.anchorNode || !rootElement.contains(selection.anchorNode)) {
        return null
    }

    return getClosestEditableBlockElement(getElementForNode(selection.anchorNode))
}

/** The subset of Range that StaticRange (from InputEvent.getTargetRanges) also implements. */
type EditTargetRange = Pick<Range, 'collapsed' | 'startContainer' | 'endContainer'>

/**
 * Whether a native input event would edit content across inline-editable element boundaries.
 * The browser implements such edits by restructuring the DOM in place (merging two `<li>`
 * elements, joining table cells), which desyncs the React-managed element tree and makes the
 * next React commit throw removeChild/insertBefore DOM exceptions — so these browser defaults
 * must never be allowed to run.
 */
export function inputEventCrossesInlineEditableBoundary(event: InputEvent, rootElement: HTMLElement): boolean {
    const eventWithTargetRanges = event as InputEvent & { getTargetRanges?: () => EditTargetRange[] }
    const targetRanges =
        typeof eventWithTargetRanges.getTargetRanges === 'function' ? eventWithTargetRanges.getTargetRanges() : []
    if (targetRanges.length) {
        return targetRanges.some((targetRange) => rangeCrossesInlineEditableBoundary(targetRange, rootElement))
    }

    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return false
    }

    return rangeCrossesInlineEditableBoundary(selection.getRangeAt(0), rootElement)
}

function rangeCrossesInlineEditableBoundary(range: EditTargetRange, rootElement: HTMLElement): boolean {
    if (range.collapsed || !rootElement.contains(range.startContainer) || !rootElement.contains(range.endContainer)) {
        return false
    }

    const startElement = getClosestEditableBlockElement(getElementForNode(range.startContainer))
    const endElement = getClosestEditableBlockElement(getElementForNode(range.endContainer))
    return !startElement || !endElement || startElement !== endElement
}

export function getCollapsedSelectionRestoreRequest(
    selection: Selection | null,
    rootElement: HTMLElement
): RestoreSelectionRequest | null {
    if (!selection || !selection.isCollapsed) {
        return null
    }

    const element = getInlineEditableElementForSelection(selection, rootElement)
    const nodeId = element?.dataset.markdownNotebookNodeId
    if (!element || !nodeId) {
        return null
    }

    const range = getSelectionRange(element, nodeId)
    if (!range) {
        return null
    }

    const offset = range.end
    const listItemIndex = element.dataset.markdownNotebookListItemIndex
    if (listItemIndex !== undefined) {
        return {
            nodeId,
            listItemIndex: Number(listItemIndex),
            listItemId: element.dataset.markdownNotebookListItemId,
            start: offset,
            end: offset,
        }
    }

    const tableSection = element.dataset.markdownNotebookTableSection
    const tableRowIndex = element.dataset.markdownNotebookTableRowIndex
    const tableColumnIndex = element.dataset.markdownNotebookTableColumnIndex
    if (
        (tableSection === 'header' || tableSection === 'body') &&
        tableRowIndex !== undefined &&
        tableColumnIndex !== undefined
    ) {
        return {
            nodeId,
            tableCell: {
                section: tableSection,
                rowIndex: Number(tableRowIndex),
                columnIndex: Number(tableColumnIndex),
            },
            start: offset,
            end: offset,
        }
    }

    return { nodeId, start: offset, end: offset }
}

export function getSelectedNotebookMarkdown(
    selection: Selection | null,
    notebookElement: HTMLElement,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>,
    listItemRefs: Record<string, HTMLElement | null>
): string | null {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return null
    }

    const range = selection.getRangeAt(0)
    if (!rangeIntersectsNode(range, notebookElement)) {
        return null
    }

    const selectedNodes: NotebookBlockNode[] = []
    nodes.forEach((node) => {
        const element = blockRefs[node.id]
        if (!element || !rangeIntersectsNode(range, element)) {
            return
        }

        if (isTextBlockNode(node)) {
            const selectedTextNode = getSelectedTextBlockNode(node, element, range)
            if (selectedTextNode) {
                selectedNodes.push(selectedTextNode)
            }
            return
        }

        if (node.type === 'list') {
            const selectedListNode = getSelectedListBlockNode(node, range, listItemRefs)
            if (selectedListNode) {
                selectedNodes.push(selectedListNode)
            }
            return
        }

        if (node.type === 'table') {
            selectedNodes.push(node)
            return
        }

        selectedNodes.push(node)
    })

    if (!selectedNodes.length) {
        return null
    }

    return serializeNotebookNodes(selectedNodes)
}

export function getSelectedTextRanges(
    selection: Selection | null,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>
): FloatingToolbarTextRange[] {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return []
    }

    return nodes.flatMap((node) => {
        if (!isTextBlockNode(node)) {
            return []
        }

        const element = blockRefs[node.id]
        const range = element ? getSelectionRange(element, node.id) : null
        if (!range || range.start === range.end) {
            return []
        }

        return [{ node, range }]
    })
}

export function getSelectedListItemRanges(
    selection: Selection | null,
    nodes: NotebookBlockNode[],
    listItemRefs: Record<string, HTMLElement | null>
): FloatingToolbarListItemRange[] {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return []
    }

    return nodes.flatMap((node) => {
        if (node.type !== 'list') {
            return []
        }

        return node.items.flatMap((_, itemIndex) => {
            const element = listItemRefs[getListItemRefKey(node.id, itemIndex)]
            const range = element ? getSelectionRange(element, node.id) : null
            if (!range || range.start === range.end) {
                return []
            }

            return [{ node, itemIndex, range }]
        })
    })
}

export function getSelectedCodeRanges(
    selection: Selection | null,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>
): FloatingToolbarCodeRange[] {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return []
    }

    return nodes.flatMap((node) => {
        if (node.type !== 'code') {
            return []
        }

        const element = blockRefs[node.id]
        const range = element ? getSelectionRange(element, node.id) : null
        if (!range || range.start === range.end) {
            return []
        }

        return [{ node, range }]
    })
}

export function getSelectedComponentNodeIds(
    selection: Selection | null,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>
): Set<string> {
    const selectedComponentNodeIds = new Set<string>()
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return selectedComponentNodeIds
    }

    const range = selection.getRangeAt(0)
    nodes.forEach((node) => {
        if (node.type !== 'component') {
            return
        }

        const element = blockRefs[node.id]
        if (!element || !rangeIntersectsNode(range, element) || isSelectionInsideElement(selection, element)) {
            return
        }

        selectedComponentNodeIds.add(node.id)
    })

    return selectedComponentNodeIds
}

export function getFocusedComponentNode(
    element: Element | null,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>
): NotebookComponentBlockNode | null {
    if (!(element instanceof HTMLElement)) {
        return null
    }

    return (
        nodes.find(
            (node): node is NotebookComponentBlockNode => node.type === 'component' && blockRefs[node.id] === element
        ) ?? null
    )
}

export function getComponentNodeForSelection(
    selection: Selection | null,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>
): NotebookComponentBlockNode | null {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return null
    }

    return (
        nodes.find((node): node is NotebookComponentBlockNode => {
            if (node.type !== 'component') {
                return false
            }

            const element = blockRefs[node.id]
            return !!element && isSelectionInsideElement(selection, element)
        }) ?? null
    )
}

export function isSelectionInsideElement(selection: Selection | null, element: HTMLElement): boolean {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return false
    }

    const range = selection.getRangeAt(0)
    return element.contains(range.startContainer) && element.contains(range.endContainer)
}

export function selectionMatchesRange(selection: Selection | null, expectedRange: Range): boolean {
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        return false
    }

    try {
        const range = selection.getRangeAt(0)
        return (
            range.compareBoundaryPoints(Range.START_TO_START, expectedRange) === 0 &&
            range.compareBoundaryPoints(Range.END_TO_END, expectedRange) === 0
        )
    } catch {
        return false
    }
}

export function isSelectionAnchoredInsideElement(selection: Selection | null, element: HTMLElement): boolean {
    return Boolean(
        selection?.anchorNode &&
        selection.focusNode &&
        element.contains(selection.anchorNode) &&
        element.contains(selection.focusNode)
    )
}

export function getSelectedTextBlockNode(
    node: NotebookTextBlockNode,
    element: HTMLElement,
    range: Range
): NotebookTextBlockNode | null {
    const selectedChildren = getSelectedInlineNodes(node.children, element, range)

    if (!selectedChildren.length) {
        return null
    }

    return { ...node, children: selectedChildren }
}

export function getSelectedListBlockNode(
    node: NotebookListBlockNode,
    range: Range,
    listItemRefs: Record<string, HTMLElement | null>
): NotebookListBlockNode | null {
    const selectedItems = node.items.flatMap((item, index) => {
        const element = item.id
            ? (listItemRefs[getListItemRefKey(node.id, item.id)] ?? listItemRefs[getListItemRefKey(node.id, index)])
            : listItemRefs[getListItemRefKey(node.id, index)]
        if (!element || !rangeIntersectsNode(range, element)) {
            return []
        }

        const selectedChildren = getSelectedInlineNodes(item.children, element, range)
        return selectedChildren.length ? [{ ...item, children: selectedChildren }] : []
    })

    if (!selectedItems.length) {
        return null
    }

    const minimumDepth = Math.min(...selectedItems.map((item) => item.depth))
    return {
        ...node,
        items: selectedItems.map((item) => ({ ...item, depth: item.depth - minimumDepth })),
    }
}

export function getSelectedInlineNodes(
    nodes: NotebookInlineNode[],
    element: HTMLElement,
    range: Range
): NotebookInlineNode[] {
    const textLength = getInlineText(nodes).length
    const selectionStart = element.contains(range.startContainer)
        ? getTextOffset(element, range.startContainer, range.startOffset)
        : 0
    const selectionEnd = element.contains(range.endContainer)
        ? getTextOffset(element, range.endContainer, range.endOffset)
        : textLength
    const normalizedStart = Math.max(0, Math.min(selectionStart, textLength))
    const normalizedEnd = Math.max(normalizedStart, Math.min(selectionEnd, textLength))
    const [, selectedAndAfter] = splitInlineNodesAt(nodes, normalizedStart)
    const [selectedChildren] = splitInlineNodesAt(selectedAndAfter, normalizedEnd - normalizedStart)

    return selectedChildren
}

export function getInlineLinkPasteResult(
    element: HTMLElement,
    nodeId: string,
    children: NotebookInlineNode[],
    plainText: string
): InlineLinkPasteResult | null {
    const href = sanitizeNotebookLinkHref(plainText)
    if (!href) {
        return null
    }

    const selection = getSelectionRange(element, nodeId)
    if (!selection) {
        return null
    }

    const textLength = getInlineText(children).length
    const selectionStart = Math.max(0, Math.min(Math.min(selection.start, selection.end), textLength))
    const selectionEnd = Math.max(selectionStart, Math.min(Math.max(selection.start, selection.end), textLength))
    if (selectionStart === selectionEnd) {
        return null
    }

    const [beforeSelection, selectionAndAfter] = splitInlineNodesAt(children, selectionStart)
    const [selectedChildren, afterSelection] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
    if (!getInlineText(selectedChildren)) {
        return null
    }

    return {
        children: normalizeInlineNodes([
            ...beforeSelection,
            ...applyLinkMarkToInlineNodes(selectedChildren, href),
            ...afterSelection,
        ]),
        start: selectionStart,
        end: selectionEnd,
    }
}

export function rangeIntersectsNode(range: Range, node: Node): boolean {
    try {
        return range.intersectsNode(node)
    } catch {
        return false
    }
}

export function isNativeEditableElement(element: HTMLElement): boolean {
    return Boolean(element.closest('input, textarea, select'))
}

export function isFormattingToolbarFocused(): boolean {
    return (
        document.activeElement instanceof HTMLElement &&
        Boolean(document.activeElement.closest('.MarkdownNotebook__format-toolbar'))
    )
}

export function findTextPosition(root: HTMLElement, offset: number): { node: Node; offset: number } {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let remaining = offset
    let current = walker.nextNode()

    while (current) {
        const length = current.textContent?.length ?? 0
        if (remaining <= length) {
            return { node: current, offset: remaining }
        }
        remaining -= length
        current = walker.nextNode()
    }

    return { node: root, offset: root.childNodes.length }
}
