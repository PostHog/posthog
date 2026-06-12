import { makeEmptyParagraph } from './markdown'
import { NotebookBlockNode, NotebookListBlockNode, NotebookListItem, NotebookTextBlockNode } from './types'

export type RenderedListItem = NotebookListItem & {
    index: number
    keyPath: string
    childrenItems: RenderedListItem[]
}

export function getListItemRefKey(nodeId: string, itemKey: string | number): string {
    return `${nodeId}:${String(itemKey)}`
}

export function buildRenderedListItems(items: NotebookListItem[]): RenderedListItem[] {
    const rootItems: RenderedListItem[] = []
    const stack: RenderedListItem[] = []

    items.forEach((item, index) => {
        const normalizedDepth = Math.max(0, item.depth)
        while (stack.length && normalizedDepth <= stack[stack.length - 1].depth) {
            stack.pop()
        }

        const parent = stack[stack.length - 1]
        const siblingIndex = parent ? parent.childrenItems.length : rootItems.length
        const renderedItem: RenderedListItem = {
            ...item,
            depth: normalizedDepth,
            index,
            keyPath: parent ? `${parent.keyPath}.${String(siblingIndex)}` : String(siblingIndex),
            childrenItems: [],
        }

        if (parent) {
            parent.childrenItems.push(renderedItem)
        } else {
            rootItems.push(renderedItem)
        }
        stack.push(renderedItem)
    })

    return rootItems
}

export function getOrderedListStart(
    items: NotebookListItem[],
    ordered: boolean,
    fallbackStart?: number
): number | undefined {
    if (!ordered) {
        return undefined
    }

    return items.find((item) => item.depth === 0 && (item.ordered ?? ordered))?.start ?? fallbackStart ?? 1
}

export function normalizeListItemDepths(items: NotebookListItem[]): NotebookListItem[] {
    const minimumDepth = Math.min(...items.map((item) => Math.max(0, item.depth)))
    if (!Number.isFinite(minimumDepth) || minimumDepth <= 0) {
        return items.map((item) => ({ ...item, depth: Math.max(0, item.depth) }))
    }

    return items.map((item) => ({ ...item, depth: Math.max(0, item.depth - minimumDepth) }))
}

/**
 * Builds the nodes that replace a list when one of its items is unwrapped into a paragraph:
 * the items before it stay a list, its children move one depth up, and trailing items become a new list.
 */
export function getListItemParagraphReplacement(
    node: NotebookListBlockNode,
    targetItemIndex: number
): { replacementNodes: NotebookBlockNode[]; paragraphId: string } | null {
    const item = node.items[targetItemIndex]
    if (!item) {
        return null
    }

    const makeListNode = (
        items: NotebookListItem[],
        idSeed: string,
        idOverride?: string
    ): NotebookListBlockNode | null => {
        if (!items.length) {
            return null
        }

        const normalizedItems = normalizeListItemDepths(items)
        const ordered = normalizedItems[0]?.ordered ?? node.ordered
        return {
            ...node,
            id: idOverride ?? makeEmptyParagraph(idSeed).id,
            ordered,
            start: getOrderedListStart(normalizedItems, ordered, node.start),
            items: normalizedItems,
        }
    }

    const subtreeEndIndex = getListItemSubtreeEndIndex(node.items, targetItemIndex)
    const beforeListNode = makeListNode(node.items.slice(0, targetItemIndex), `before-list-${node.id}`, node.id)
    const paragraph: NotebookTextBlockNode = {
        id: beforeListNode ? makeEmptyParagraph(`unlisted-${node.id}`).id : node.id,
        type: 'paragraph',
        children: item.children,
    }
    const childItems = node.items
        .slice(targetItemIndex + 1, subtreeEndIndex)
        .map((childItem) => ({ ...childItem, depth: Math.max(0, childItem.depth - 1) }))
    const afterListNode = makeListNode([...childItems, ...node.items.slice(subtreeEndIndex)], `after-list-${node.id}`)
    const replacementNodes: NotebookBlockNode[] = []
    if (beforeListNode) {
        replacementNodes.push(beforeListNode)
    }
    replacementNodes.push(paragraph)
    if (afterListNode) {
        replacementNodes.push(afterListNode)
    }

    return { replacementNodes, paragraphId: paragraph.id }
}

/** Shifts a list item and its subtree one depth step in or out, or returns null when the shift is not allowed. */
export function shiftListItemSubtreeDepth(
    items: NotebookListItem[],
    itemIndex: number,
    direction: 'in' | 'out',
    listOrdered: boolean
): NotebookListItem[] | null {
    const item = items[itemIndex]
    if (!item) {
        return null
    }

    const maximumDepth = itemIndex === 0 ? 0 : items[itemIndex - 1].depth + 1
    const nextDepth = direction === 'in' ? Math.min(item.depth + 1, maximumDepth) : Math.max(0, item.depth - 1)
    const depthDelta = nextDepth - item.depth
    if (depthDelta === 0) {
        return null
    }

    const subtreeEndIndex = getListItemSubtreeEndIndex(items, itemIndex)
    return items.map((currentItem, index) => {
        if (index < itemIndex || index >= subtreeEndIndex) {
            return currentItem
        }

        const nextItem = { ...currentItem, depth: Math.max(0, currentItem.depth + depthDelta) }
        if (index === itemIndex && depthDelta > 0 && (nextItem.ordered ?? listOrdered)) {
            return { ...nextItem, start: undefined }
        }

        return nextItem
    })
}

export function getListItemSubtreeEndIndex(items: NotebookListItem[], itemIndex: number): number {
    const item = items[itemIndex]
    if (!item) {
        return itemIndex
    }

    let nextIndex = itemIndex + 1
    while (nextIndex < items.length && items[nextIndex].depth > item.depth) {
        nextIndex += 1
    }
    return nextIndex
}

export function getListItemIndex(items: NotebookListItem[], fallbackIndex: number, itemId?: string): number {
    if (itemId) {
        const itemIndex = items.findIndex((item) => item.id === itemId)
        if (itemIndex !== -1) {
            return itemIndex
        }
    }

    return fallbackIndex
}
