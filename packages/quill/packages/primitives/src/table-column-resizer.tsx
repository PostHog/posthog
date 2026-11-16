import { mergeProps } from '@base-ui/react/merge-props'
import * as React from 'react'

import { cn } from './lib/utils'
import { ResizeGrip } from './resizable'
import { previewTableColumnWidth } from './table'

// Enough for a short label and its sort icon.
export const MIN_TABLE_COLUMN_WIDTH = 64
const KEYBOARD_STEP = 16

type TableColumnResizerProps = Omit<React.ComponentProps<'div'>, 'children' | 'defaultValue'> & {
    /** The column's width in pixels, for assistive technology. Omit it while the column still fits its content. */
    value?: number
    /** Called once with the final width in pixels, when a drag ends or on a press of an arrow key. Set your state here. */
    onValueCommitted: (width: number) => void
    /** Smallest width in pixels. */
    min?: number
    /** Largest width in pixels. */
    max?: number
    /** Called before the first change of a drag or key press, for a table that fixes its widths only then. */
    onResizeStart?: () => void
    /** Called on a double click, to give the column back its default width. */
    onReset?: () => void
}

/**
 * The edge of a column, for a `TableHead` to hold as its last child, in a `Table` with `columnWidths`: a line that shows
 * while the header is hovered, and a handle that shows while its own header cell is. Drags with the pointer and moves
 * with the arrow keys.
 *
 * A drag moves the column through the `Table`, once per frame, and only reports the result when it ends. Rendering on
 * every move would render every row, which takes far longer than a frame in a large table.
 */
const TableColumnResizer = React.forwardRef<HTMLDivElement, TableColumnResizerProps>(function TableColumnResizer(
    {
        className,
        value,
        onValueCommitted,
        min = MIN_TABLE_COLUMN_WIDTH,
        max = Infinity,
        onResizeStart,
        onReset,
        'aria-label': ariaLabel = 'Resize column',
        ...props
    },
    ref
) {
    const [resizing, setResizing] = React.useState(false)
    const clamp = (width: number): number => Math.round(Math.min(max, Math.max(min, width)))
    const currentWidth = (element: Element): number =>
        value ?? element.closest('th')?.getBoundingClientRect().width ?? min
    // The right edge of a column is its left edge in a right-to-left table, so a drag runs the other way.
    const inlineDirection = (element: Element): number => (getComputedStyle(element).direction === 'rtl' ? -1 : 1)

    const onPointerDown = (event: React.PointerEvent<HTMLDivElement>): void => {
        if (event.button !== 0) {
            return
        }
        const grip = event.currentTarget
        const head = grip.closest('th')
        const table = grip.closest('table')
        const startX = event.clientX
        const startWidth = currentWidth(grip)
        const direction = inlineDirection(grip)
        let width = startWidth
        let started = false
        let frame = 0

        const applyWidth = (): void => {
            frame = 0
            if (table && head) {
                previewTableColumnWidth(table, head.cellIndex, width)
            }
            grip.setAttribute('aria-valuenow', String(width))
        }

        const onMove = (move: PointerEvent): void => {
            if (!started) {
                started = true
                onResizeStart?.()
            }
            width = clamp(startWidth + (move.clientX - startX) * direction)
            frame ||= requestAnimationFrame(applyWidth)
        }

        const onEnd = (): void => {
            grip.removeEventListener('pointermove', onMove)
            grip.removeEventListener('pointerup', onEnd)
            grip.removeEventListener('pointercancel', onEnd)
            cancelAnimationFrame(frame)
            setResizing(false)
            if (started) {
                applyWidth()
                onValueCommitted(width)
            }
        }

        grip.setPointerCapture?.(event.pointerId)
        setResizing(true)
        grip.addEventListener('pointermove', onMove)
        grip.addEventListener('pointerup', onEnd)
        grip.addEventListener('pointercancel', onEnd)
    }

    const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
            return
        }
        event.preventDefault()
        const step = (event.key === 'ArrowLeft' ? -KEYBOARD_STEP : KEYBOARD_STEP) * inlineDirection(event.currentTarget)
        onResizeStart?.()
        onValueCommitted(clamp(currentWidth(event.currentTarget) + step))
    }

    return (
        <ResizeGrip
            ref={ref}
            size="sm"
            data-slot="table-column-resizer"
            data-resizing={resizing ? '' : undefined}
            tabIndex={0}
            aria-label={ariaLabel}
            aria-valuenow={value}
            aria-valuemin={min}
            aria-valuemax={max === Infinity ? undefined : max}
            className={cn('quill-table__resizer', className)}
            {...mergeProps<'div'>(
                {
                    onPointerDown,
                    // Stops a drag selecting the header text. It also keeps focus, and its ring, away from a pointer drag.
                    onMouseDown: (event) => event.preventDefault(),
                    onKeyDown,
                    onDoubleClick: () => onReset?.(),
                },
                props
            )}
        />
    )
})

TableColumnResizer.displayName = 'TableColumnResizer'

export { TableColumnResizer }
