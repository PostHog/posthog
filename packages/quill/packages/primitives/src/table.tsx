import * as React from 'react'

import './table.css'
import { cn } from './lib/utils'

type Sticky = 'left' | 'right'

// Reflects which edges of `viewport` still have hidden content as
// `data-scroll-{top,right,bottom,left}` on `root` (the non-scrolling wrapper, so
// edge-shadow overlays on it stay fixed while content scrolls). CSS keys the
// frozen-header/column and generic viewport-edge shadows off these — robust
// everywhere, unlike the `scroll-state()` container query (recent Chromium only).
function useScrollEdges(
    rootRef: React.RefObject<HTMLDivElement | null>,
    viewportRef: React.RefObject<HTMLDivElement | null>
): void {
    React.useEffect(() => {
        const root = rootRef.current
        const viewport = viewportRef.current
        if (!root || !viewport) {
            return
        }
        const updateEdges = (): void => {
            const { scrollTop, scrollLeft, scrollWidth, clientWidth, scrollHeight, clientHeight } = viewport
            // scrollLeft is negative when scrolled from the start in RTL; abs() normalizes it.
            const left = Math.abs(scrollLeft)
            root.toggleAttribute('data-scroll-top', scrollTop > 0)
            root.toggleAttribute('data-scroll-bottom', Math.ceil(scrollTop + clientHeight) < scrollHeight)
            root.toggleAttribute('data-scroll-left', left > 0)
            root.toggleAttribute('data-scroll-right', Math.ceil(left + clientWidth) < scrollWidth)
        }
        updateEdges()
        viewport.addEventListener('scroll', updateEdges, { passive: true })
        // Catch viewport and content size changes (rows added, columns resized).
        const observer = new ResizeObserver(updateEdges)
        observer.observe(viewport)
        for (const child of Array.from(viewport.children)) {
            observer.observe(child)
        }
        return () => {
            viewport.removeEventListener('scroll', updateEdges)
            observer.disconnect()
        }
    }, [rootRef, viewportRef])
}

function Table({
    className,
    tableClassName,
    stickyHeader = false,
    ...props
}: React.ComponentProps<'table'> & {
    /**
     * `true` — header sticks within the table's own scroll viewport (needs a
     * bounded height). `'page'` — header sticks to document scroll instead; the
     * wrappers drop their scroll container so stickiness escapes to the page.
     * Offset it past fixed page chrome with `--quill-table-sticky-top`.
     */
    stickyHeader?: boolean | 'page'
    /** Classes for the inner <table>. Size/scroll go on the container via `className`. */
    tableClassName?: string
}): React.ReactElement {
    const rootRef = React.useRef<HTMLDivElement | null>(null)
    const viewportRef = React.useRef<HTMLDivElement | null>(null)
    useScrollEdges(rootRef, viewportRef)
    // `className` sizes the non-scrolling root (which clips + hosts the fixed edge
    // shadows); the inner viewport owns the scroll. Sticky header/columns position
    // against the viewport.
    return (
        <div
            ref={rootRef}
            data-quill
            data-slot="table-container"
            data-page-sticky={stickyHeader === 'page' ? '' : undefined}
            className={cn('quill-table__root', className)}
        >
            <div ref={viewportRef} data-slot="table-viewport" className="quill-table__viewport">
                <table
                    data-slot="table"
                    data-sticky-header={stickyHeader ? '' : undefined}
                    className={cn('quill-table', tableClassName)}
                    {...props}
                />
            </div>
        </div>
    )
}

function TableHeader({ className, ...props }: React.ComponentProps<'thead'>): React.ReactElement {
    return <thead data-slot="table-header" className={cn('quill-table__header', className)} {...props} />
}

function TableBody({ className, ...props }: React.ComponentProps<'tbody'>): React.ReactElement {
    return <tbody data-slot="table-body" className={cn('quill-table__body', className)} {...props} />
}

function TableFooter({ className, ...props }: React.ComponentProps<'tfoot'>): React.ReactElement {
    return <tfoot data-slot="table-footer" className={cn('quill-table__footer', className)} {...props} />
}

function TableRow({ className, ...props }: React.ComponentProps<'tr'>): React.ReactElement {
    return <tr data-slot="table-row" className={cn('quill-table__row', className)} {...props} />
}

function TableHead({
    className,
    sticky,
    ...props
}: React.ComponentProps<'th'> & { sticky?: Sticky }): React.ReactElement {
    return (
        <th
            data-slot="table-head"
            data-sticky={sticky}
            className={cn('quill-table__head', className)}
            {...props}
        />
    )
}

function TableCell({
    className,
    sticky,
    ...props
}: React.ComponentProps<'td'> & { sticky?: Sticky }): React.ReactElement {
    return (
        <td
            data-slot="table-cell"
            data-sticky={sticky}
            className={cn('quill-table__cell', className)}
            {...props}
        />
    )
}

function TableCaption({ className, ...props }: React.ComponentProps<'caption'>): React.ReactElement {
    return <caption data-slot="table-caption" className={cn('quill-table__caption', className)} {...props} />
}

export { Table, TableHeader, TableBody, TableFooter, TableHead, TableRow, TableCell, TableCaption }
