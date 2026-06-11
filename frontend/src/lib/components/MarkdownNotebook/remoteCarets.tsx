import { MutableRefObject, RefObject, useLayoutEffect, useState } from 'react'

import {
    findTextPosition,
    getCollapsedSelectionRestoreRequest,
    getElementLineHeight,
    getSelectionClientRect,
} from './domSelection'
import { getListItemRefKey } from './listModel'
import { NotebookBlockNode } from './types'

/**
 * A caret location in coordinates that transfer between clients. Node ids are
 * remapped per client by reconciliation history, so they can't cross the wire —
 * but two clients with identical markdown always parse the same block sequence,
 * making (node index, plain-text offset) stable. Receivers clamp on resolve, so
 * briefly skewed versions degrade to a slightly-off caret instead of an error.
 */
export type MarkdownNotebookCaretPosition = {
    nodeIndex: number
    /** Offset in the plain text of the focused editable element, in UTF-16 code units. */
    offset?: number
    /** Set when the caret is inside a list block: the focused item's index. */
    listItemIndex?: number
}

export type RemoteNotebookCaret = {
    clientId: string
    userName: string
    color: string
    position: MarkdownNotebookCaretPosition
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

export type RemoteCaretLayout = {
    top: number
    left: number
    height: number
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
    let rect: DOMRect | null = null
    if (position.offset !== undefined) {
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

    useLayoutEffect(() => {
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
        <div className="MarkdownNotebook__remote-carets" aria-hidden="true">
            {carets.map((caret) => {
                const layout = layouts[caret.clientId]
                if (!layout) {
                    return null
                }
                return (
                    <div
                        key={caret.clientId}
                        className="MarkdownNotebook__remote-caret"
                        style={
                            {
                                top: layout.top,
                                left: layout.left,
                                height: layout.height,
                                '--remote-presence-color': caret.color,
                            } as React.CSSProperties
                        }
                    >
                        <span className="MarkdownNotebook__remote-caret-flag">{caret.userName}</span>
                    </div>
                )
            })}
        </div>
    )
}
