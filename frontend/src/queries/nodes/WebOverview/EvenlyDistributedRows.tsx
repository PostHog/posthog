import clsx from 'clsx'
import React, { useCallback, useEffect, useRef, useState } from 'react'

// see https://github.com/PostHog/posthog/pull/20359/files#r1490894232 for a visual example of what this is trying to
// solve
// if 5 items are to be evenly distributed across a container that has space for 4, just naively using flex will result
// in a 4-1 split, whereas this component will distribute them 3-2
// Sadly, the technology to do this with pure CSS has not been invented or discovered yet.

export const EvenlyDistributedRows = ({
    children,
    minWidthRems,
    className,
    maxItemsPerRow,
}: {
    children: React.ReactNode[]
    minWidthRems: number
    className: string
    maxItemsPerRow?: number
}): JSX.Element => {
    const [rowLayout, setRowLayout] = useState<{ itemsPerRow: number; numRows: number }>()
    // Measured on a wrapper that's never restyled, so resizing the grid inside it can't feed back into
    // the observed box (mutating the observed element from within its own ResizeObserver callback is
    // what triggers "ResizeObserver loop" oscillation).
    const containerRef = useRef<HTMLDivElement>(null)

    const updateSize = useCallback((): void => {
        if (!containerRef.current) {
            return
        }
        const pxPerRem = parseFloat(getComputedStyle(document.documentElement).fontSize)
        const minWidthPx = minWidthRems * pxPerRem
        const containerWidthPx = containerRef.current.offsetWidth

        const calculatedMaxItemsPerRow = Math.floor(containerWidthPx / minWidthPx)
        const effectiveMaxItemsPerRow = maxItemsPerRow
            ? Math.min(calculatedMaxItemsPerRow, maxItemsPerRow)
            : calculatedMaxItemsPerRow

        // Distribute items evenly
        // e.g. if we can have 4 elements per row and have 9 items
        // prefer 3,3,3 to 4,4,1
        const numRows = Math.ceil(children.length / effectiveMaxItemsPerRow)
        const itemsPerRow = Math.min(Math.ceil(children.length / numRows), effectiveMaxItemsPerRow)

        setRowLayout((prev) =>
            prev && prev.itemsPerRow === itemsPerRow && prev.numRows === numRows ? prev : { numRows, itemsPerRow }
        )
    }, [containerRef, minWidthRems, children.length, maxItemsPerRow])

    useEffect(() => {
        const element = containerRef.current
        if (!element) {
            return
        }

        updateSize()

        let resizeObserver: ResizeObserver | undefined
        let rafId: number | null = null
        if (typeof ResizeObserver !== 'undefined') {
            resizeObserver = new ResizeObserver(() => {
                // Coalesce bursts of notifications into one recalculation per frame.
                if (rafId != null) {
                    return
                }
                rafId = requestAnimationFrame(() => {
                    rafId = null
                    updateSize()
                })
            })
        }
        resizeObserver?.observe(element)

        return () => {
            if (rafId != null) {
                cancelAnimationFrame(rafId)
            }
            resizeObserver?.disconnect()
        }
    }, [updateSize])

    return (
        <div className="w-full" ref={containerRef}>
            <div
                className={clsx('grid', className)}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ gridTemplateColumns: `repeat(${rowLayout?.itemsPerRow ?? 1}, 1fr)` }}
            >
                {rowLayout ? children : null}
            </div>
        </div>
    )
}
