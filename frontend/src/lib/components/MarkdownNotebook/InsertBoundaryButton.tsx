import clsx from 'clsx'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { isInlineInsertMenuRow, isTextBlockNode } from './documentModel'
import { NotebookBlockNode } from './types'

export function InsertBoundaryButton({
    boundaryIndex,
    focusPreviousNodeAtBoundaryEnd,
    isAvailable,
    isGapClickable,
    isVisible,
    openInsertMenuAtBoundary,
    setActiveBoundaryIndex,
}: {
    boundaryIndex: number
    focusPreviousNodeAtBoundaryEnd: (boundaryIndex: number) => void
    isAvailable: boolean
    isGapClickable: boolean
    isVisible: boolean
    openInsertMenuAtBoundary: (boundaryIndex: number) => void
    setActiveBoundaryIndex: (boundaryIndex: number) => void
}): JSX.Element {
    return (
        <div
            className={clsx(
                'MarkdownNotebook__insert-boundary',
                isAvailable && 'MarkdownNotebook__insert-boundary--available',
                isAvailable && isGapClickable && 'MarkdownNotebook__insert-boundary--gap-clickable',
                isAvailable && !isGapClickable && 'MarkdownNotebook__insert-boundary--focuses-previous'
            )}
            contentEditable={false}
            onMouseEnter={() => setActiveBoundaryIndex(boundaryIndex)}
            // Reveal on keyboard focus, mirroring the mouse-hover reveal.
            onFocusCapture={() => setActiveBoundaryIndex(boundaryIndex)}
            onMouseDown={(event) => {
                if (
                    !isAvailable ||
                    event.button !== 0 ||
                    (event.target instanceof HTMLElement && event.target.closest('button'))
                ) {
                    return
                }

                event.preventDefault()
                event.stopPropagation()
                if (!isGapClickable) {
                    focusPreviousNodeAtBoundaryEnd(boundaryIndex)
                    return
                }

                openInsertMenuAtBoundary(boundaryIndex)
            }}
        >
            <div
                className="MarkdownNotebook__insert-boundary-hover-zone"
                aria-hidden="true"
                onMouseEnter={() => setActiveBoundaryIndex(boundaryIndex)}
                onMouseMove={() => setActiveBoundaryIndex(boundaryIndex)}
            />
            {isAvailable ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconPlus />}
                    className={clsx(
                        'MarkdownNotebook__insert-boundary-button',
                        isVisible && 'MarkdownNotebook__insert-boundary-button--visible'
                    )}
                    tooltip="Add block"
                    onClick={() => openInsertMenuAtBoundary(boundaryIndex)}
                    aria-label="Add block"
                    data-boundary-index={boundaryIndex}
                    tabIndex={0}
                />
            ) : null}
        </div>
    )
}

export function isInsertBoundaryAvailable(
    nodes: NotebookBlockNode[],
    boundaryIndex: number,
    insertMenuNodeId?: string
): boolean {
    if (boundaryIndex <= 0) {
        return false
    }

    const previousNode = nodes[boundaryIndex - 1]
    const nextNode = nodes[boundaryIndex]
    if (
        insertMenuNodeId !== undefined &&
        (previousNode?.id === insertMenuNodeId || nextNode?.id === insertMenuNodeId)
    ) {
        return false
    }

    const previousNodeIsInlineInsertRow = isInlineInsertMenuRow(previousNode)
    const nextNodeIsInlineInsertRow = isInlineInsertMenuRow(nextNode)
    if (nextNodeIsInlineInsertRow) {
        return false
    }

    if (previousNodeIsInlineInsertRow) {
        return !!nextNode && !isTextBlockNode(nextNode)
    }

    return true
}

export function isInsertBoundaryVisible(
    nodes: NotebookBlockNode[],
    boundaryIndex: number,
    activeBoundaryIndex: number | null,
    focusedRowIndex: number | null,
    insertMenuNodeId?: string
): boolean {
    if (
        activeBoundaryIndex === null ||
        focusedRowIndex !== null ||
        insertMenuNodeId !== undefined ||
        !isInsertBoundaryAvailable(nodes, boundaryIndex, insertMenuNodeId)
    ) {
        return false
    }

    return boundaryIndex === activeBoundaryIndex
}

export function getClosestInsertBoundaryIndex(rowElement: HTMLElement, rowIndex: number, clientY: number): number {
    const rowRect = rowElement.getBoundingClientRect()

    if (rowRect.height <= 0) {
        return rowIndex
    }

    return clientY <= rowRect.top + rowRect.height / 2 ? rowIndex : rowIndex + 1
}
