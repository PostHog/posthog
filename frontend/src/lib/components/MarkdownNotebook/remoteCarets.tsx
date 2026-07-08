import { MutableRefObject, RefObject, useEffect, useState } from 'react'

import {
    findTextPosition,
    getCollapsedSelectionRestoreRequest,
    getElementLineHeight,
    getSelectionClientRect,
} from './domSelection'
import { getListItemRefKey } from './listModel'
import { getTextChanges, mapTextIndex } from './textChanges'
import { NotebookBlockNode, NotebookDocument } from './types'
import { getInlineText } from './utils'

/**
 * A caret location in coordinates that transfer between clients. Node ids are
 * remapped per client by reconciliation history, so they can't cross the wire —
 * but two clients with identical markdown always parse the same block sequence,
 * making (node index, plain-text offset) stable. Receivers clamp on resolve, so
 * briefly skewed versions degrade to a slightly-off caret instead of an error.
 */
export type MarkdownNotebookCaretPosition = {
    nodeIndex: number
    /**
     * Offset in the plain text of the focused editable element, in UTF-16 code units.
     * Absent for block-level positions (components, tables): the user is "on" the
     * block without a text caret, and receivers render an outline instead of a caret.
     */
    offset?: number
    /** Set when the caret is inside a list block: the focused item's index. */
    listItemIndex?: number
}

export type RemoteNotebookCaret = {
    clientId: string
    userName: string
    color: string
    position: MarkdownNotebookCaretPosition
    /** Notebook version the position was computed against, when known. */
    version?: number
    isAI?: boolean
    isAIThinking?: boolean
    isFading?: boolean
}

/**
 * Re-map a remote caret through a local document change so it moves with the text it sits
 * in — without this, a collaborator's caret stays parked at a fixed character offset while
 * locally typed text slides past it, until their next presence ping arrives.
 */
export function mapRemoteCaretPositionThroughDocumentChange(
    position: MarkdownNotebookCaretPosition,
    previousDocument: NotebookDocument,
    nextDocument: NotebookDocument
): MarkdownNotebookCaretPosition {
    const previousNode = previousDocument.nodes[position.nodeIndex]
    if (!previousNode) {
        return position
    }
    const nextNodeIndex = nextDocument.nodes.findIndex((node) => node.id === previousNode.id)
    if (nextNodeIndex === -1) {
        return position
    }
    const nextNode = nextDocument.nodes[nextNodeIndex]

    let listItemIndex = position.listItemIndex
    let previousText: string | null = null
    let nextText: string | null = null

    if (previousNode.type === 'list' && nextNode.type === 'list' && listItemIndex !== undefined) {
        const previousItem = previousNode.items[listItemIndex]
        const mappedItemIndex = previousItem?.id ? nextNode.items.findIndex((item) => item.id === previousItem.id) : -1
        if (mappedItemIndex !== -1) {
            listItemIndex = mappedItemIndex
        }
        const nextItem = nextNode.items[listItemIndex]
        previousText = previousItem ? getInlineText(previousItem.children) : null
        nextText = nextItem ? getInlineText(nextItem.children) : null
    } else if (
        (previousNode.type === 'paragraph' || previousNode.type === 'heading' || previousNode.type === 'blockquote') &&
        (nextNode.type === 'paragraph' || nextNode.type === 'heading' || nextNode.type === 'blockquote')
    ) {
        previousText = getInlineText(previousNode.children)
        nextText = getInlineText(nextNode.children)
    } else if (previousNode.type === 'code' && nextNode.type === 'code') {
        previousText = previousNode.text
        nextText = nextNode.text
    }

    let offset = position.offset
    if (offset !== undefined && previousText !== null && nextText !== null && previousText !== nextText) {
        offset = mapTextIndex(offset, getTextChanges(previousText, nextText), 'right')
    }

    if (
        nextNodeIndex === position.nodeIndex &&
        offset === position.offset &&
        listItemIndex === position.listItemIndex
    ) {
        return position
    }
    return { ...position, nodeIndex: nextNodeIndex, offset, listItemIndex }
}

export function getMarkdownNotebookCaretPosition(
    selection: Selection | null,
    rootElement: HTMLElement,
    nodes: NotebookBlockNode[]
): MarkdownNotebookCaretPosition | null {
    const request = getCollapsedSelectionRestoreRequest(selection, rootElement)
    if (!request || !('nodeId' in request)) {
        return null
    }
    const nodeIndex = nodes.findIndex((node) => node.id === request.nodeId)
    if (nodeIndex === -1) {
        return null
    }
    if (request.tableCell) {
        // Table cells get block-level precision: the caret renders at the table's edge.
        return { nodeIndex }
    }
    if (request.listItemIndex !== undefined) {
        return { nodeIndex, offset: request.start, listItemIndex: request.listItemIndex }
    }
    return { nodeIndex, offset: request.start }
}

/**
 * When the focused element isn't a text caret host (a selected component, a focused
 * divider/comment chip, anything inside a query block), report the containing block
 * as a block-level position so collaborators can see who is on it.
 */
export function getFocusedBlockCaretPosition(
    activeElement: Element | null,
    rootElement: HTMLElement,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>
): MarkdownNotebookCaretPosition | null {
    if (!activeElement || !rootElement.contains(activeElement)) {
        return null
    }

    for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex++) {
        const element = blockRefs[nodes[nodeIndex].id]
        if (element && (element === activeElement || element.contains(activeElement))) {
            return { nodeIndex }
        }
    }
    return null
}

export type RemoteCaretLayout = {
    top: number
    left: number
    height: number
    /** Set for block-level positions: render an outline of this width instead of a caret bar. */
    width?: number
}

export function resolveRemoteCaretLayout(
    position: MarkdownNotebookCaretPosition,
    nodes: NotebookBlockNode[],
    blockRefs: Record<string, HTMLElement | null>,
    listItemRefs: Record<string, HTMLElement | null>,
    containerElement: HTMLElement
): RemoteCaretLayout | null {
    const node = nodes[position.nodeIndex]
    if (!node) {
        return null
    }

    let element: HTMLElement | null
    if (node.type === 'list' && position.listItemIndex !== undefined && node.items.length > 0) {
        const itemIndex = Math.min(position.listItemIndex, node.items.length - 1)
        element = listItemRefs[getListItemRefKey(node.id, itemIndex)] ?? blockRefs[node.id]
    } else {
        element = blockRefs[node.id]
    }
    if (!element) {
        return null
    }

    const containerRect = containerElement.getBoundingClientRect()

    // Components never host a text caret, so any position on one is block-level.
    if (position.offset === undefined || node.type === 'component') {
        const blockRect = element.getBoundingClientRect()
        return {
            top: blockRect.top - containerRect.top,
            left: blockRect.left - containerRect.left,
            height: blockRect.height,
            width: blockRect.width,
        }
    }

    let rect: DOMRect | null = null
    const textLength = element.textContent?.length ?? 0
    const clampedOffset = Math.max(0, Math.min(position.offset, textLength))
    const target = findTextPosition(element, clampedOffset)
    try {
        const range = window.document.createRange()
        range.setStart(target.node, target.offset)
        range.setEnd(target.node, target.offset)
        rect = getSelectionClientRect(range)
    } catch {
        rect = null
    }

    const height = rect?.height || getElementLineHeight(element)
    const anchorRect = rect ?? element.getBoundingClientRect()
    return {
        top: anchorRect.top - containerRect.top,
        left: anchorRect.left - containerRect.left,
        height,
    }
}

export function RemoteCaretOverlay({
    carets,
    nodes,
    blockRefs,
    listItemRefs,
    containerRef,
}: {
    carets: RemoteNotebookCaret[]
    nodes: NotebookBlockNode[]
    blockRefs: MutableRefObject<Record<string, HTMLElement | null>>
    listItemRefs: MutableRefObject<Record<string, HTMLElement | null>>
    containerRef: RefObject<HTMLElement | null>
}): JSX.Element | null {
    const [layouts, setLayouts] = useState<Record<string, RemoteCaretLayout>>({})

    useEffect(() => {
        const container = containerRef.current
        if (!container) {
            return
        }

        const measure = (): void => {
            const nextLayouts: Record<string, RemoteCaretLayout> = {}
            for (const caret of carets) {
                const layout = resolveRemoteCaretLayout(
                    caret.position,
                    nodes,
                    blockRefs.current,
                    listItemRefs.current,
                    container
                )
                if (layout) {
                    nextLayouts[caret.clientId] = layout
                }
            }
            setLayouts(nextLayouts)
        }

        measure()
        // Re-measure on reflow: width changes rewrap text, async content (images, queries) shifts blocks.
        const observer = new ResizeObserver(measure)
        observer.observe(container)
        window.addEventListener('resize', measure)
        return () => {
            observer.disconnect()
            window.removeEventListener('resize', measure)
        }
    }, [carets, nodes, blockRefs, listItemRefs, containerRef])

    if (!carets.length) {
        return null
    }

    return (
        <div className="MarkdownNotebook__remote-carets" aria-hidden={true}>
            {carets.map((caret) => {
                const layout = layouts[caret.clientId]
                if (!layout) {
                    return null
                }
                const caretFlag = (
                    <span className="MarkdownNotebook__remote-caret-flag">
                        <span className="MarkdownNotebook__remote-caret-name">{caret.userName}</span>
                        {caret.isAI && caret.isAIThinking ? (
                            <span className="MarkdownNotebook__remote-caret-ai-dots">
                                <span>.</span>
                                <span>.</span>
                                <span>.</span>
                            </span>
                        ) : null}
                    </span>
                )

                if (layout.width !== undefined) {
                    // Block-level presence: the user is on a component/table, not at a text offset.
                    const style = {
                        top: layout.top,
                        left: layout.left,
                        width: layout.width,
                        height: layout.height,
                        '--remote-presence-color': caret.color,
                    } as React.CSSProperties
                    const className = caret.isFading
                        ? 'MarkdownNotebook__remote-block MarkdownNotebook__remote-block--fading'
                        : 'MarkdownNotebook__remote-block'
                    return (
                        <div key={caret.clientId} className={className} style={style}>
                            {caretFlag}
                        </div>
                    )
                }
                const style = {
                    top: layout.top,
                    left: layout.left,
                    height: layout.height,
                    '--remote-presence-color': caret.color,
                } as React.CSSProperties
                const className = caret.isFading
                    ? 'MarkdownNotebook__remote-caret MarkdownNotebook__remote-caret--fading'
                    : 'MarkdownNotebook__remote-caret'
                return (
                    <div key={caret.clientId} className={className} style={style}>
                        {caretFlag}
                    </div>
                )
            })}
        </div>
    )
}
