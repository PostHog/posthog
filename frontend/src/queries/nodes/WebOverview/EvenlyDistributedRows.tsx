import clsx from 'clsx'
import React, { useCallback, useEffect, useRef, useState } from 'react'

export const EvenlyDistributedRows = ({
    children,
    minWidthRems,
    className,
}: {
    children: React.ReactNode[]
    minWidthRems: number
    className: string
}): JSX.Element => {
    const [rowLayout, setRowLayout] = useState<{ itemsPerRow: number; numRows: number }>()
    const elementRef = useRef<HTMLDivElement>(null)

    const updateSize = useCallback((): void => {
        if (!elementRef.current) {
            return
        }
        const pxPerRem = parseFloat(getComputedStyle(document.documentElement).fontSize)
        const minWidthPx = minWidthRems * pxPerRem
        const containerWidthPx = elementRef.current.offsetWidth

        const maxItemsPerRow = Math.floor(containerWidthPx / minWidthPx)
        // Distribute items evenly
        // e.g. if we can have 4 elements per row and have 9 items
        // prefer 3,3,3 to 4,4,1
        const numRows = Math.ceil(children.length / maxItemsPerRow)
        const itemsPerRow = Math.ceil(children.length / numRows)

        setRowLayout({
            numRows,
            itemsPerRow,
        })
    }, [setRowLayout, elementRef, minWidthRems, children.length])

    useEffect(() => {
        const element = elementRef.current
        if (!element) {
            return
        }

        updateSize()

        let resizeObserver: ResizeObserver | undefined
        if (typeof ResizeObserver !== 'undefined') {
            resizeObserver = new ResizeObserver(updateSize)
        }
        resizeObserver?.observe(element)

        return () => {
            resizeObserver?.unobserve(element)
        }
    }, [updateSize])

    return (
        <div
            className={clsx('grid', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ gridTemplateColumns: `repeat(${rowLayout?.itemsPerRow ?? 1}, 1fr)` }}
            ref={elementRef}
        >
            {rowLayout ? children : null}
        </div>
    )
}
