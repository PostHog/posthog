import './table.css'

import * as React from 'react'

import { cn } from './lib/utils'

type Sticky = 'left' | 'right'
type Align = 'left' | 'center' | 'right'
type VAlign = 'top' | 'middle' | 'bottom'

// Per-cell layout shared by TableHead and TableCell. `align` is horizontal
// (text-align — also positions an inline-flex header Button), `valign` vertical
// (vertical-align). `expand` lets the column soak up leftover width in a
// `fullWidth` table (other columns size to content). Emitted as data-attrs so
// CSS owns the values; omit for the CSS default (left / middle).
type CellLayout = {
    align?: Align
    valign?: VAlign
    /** Absorb remaining width in a `fullWidth` table. Mark one column per table. */
    expand?: boolean
    /**
     * An empty last cell in each row of a `fullWidth` table with resizable columns. It fills the space the columns
     * leave, and shows only once their widths are fixed.
     */
    filler?: boolean
}

// Sets each ref (object or callback) to the same node — lets the viewport carry
// both the internal scroll-tracking ref and a caller-supplied `viewportRef`.
function setRefs<T>(node: T, ...refs: Array<React.Ref<T> | undefined>): void {
    for (const ref of refs) {
        if (typeof ref === 'function') {
            ref(node)
        } else if (ref) {
            ;(ref as React.MutableRefObject<T | null>).current = node
        }
    }
}

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

function sumWidths(widths: number[]): number {
    return widths.reduce((total, width) => total + width, 0)
}

/**
 * Moves a column to a width straight in the DOM, for each frame of a drag, because rendering there would render every
 * row. It does nothing until the table's widths are fixed.
 */
function previewTableColumnWidth(table: HTMLTableElement, index: number, width: number): void {
    const cols = Array.from(table.querySelector('colgroup')?.children ?? []) as HTMLElement[]
    const col = cols[index]
    if (!col?.style.width) {
        return
    }
    col.style.width = `${width}px`
    // A full-width table's last `col` is the filler, which has no width.
    const total = sumWidths(cols.map((c) => parseFloat(c.style.width) || 0))
    // The same property the render sets: React leaves alone a style it thinks has not changed.
    table.style[table.hasAttribute('data-full-width') ? 'minWidth' : 'width'] = `${total}px`
}

type TableProps = React.ComponentProps<'table'> & {
    /**
     * `true` — header sticks within the table's own scroll viewport (needs a
     * bounded height). `'page'` — header sticks to document scroll instead; the
     * wrappers drop their scroll container so stickiness escapes to the page.
     * Offset it past fixed page chrome with `--quill-table-sticky-top`.
     */
    stickyHeader?: boolean | 'page'
    /**
     * Stretch the table to fill its container instead of sizing to content (so it
     * never scrolls horizontally). Pair with `expand` on a column to choose which
     * one soaks up the slack; otherwise the extra width spreads across columns.
     */
    fullWidth?: boolean
    /**
     * Cell density. `'sm'` tightens the head/cell inline padding to `0.75rem`
     * (from `1rem`) so the table's edge columns line up with a `Card size="sm"`'s
     * `0.75rem` inline padding. Pair with `Card size="sm" flush`.
     */
    size?: 'default' | 'sm'
    /**
     * Makes the columns resizable, with a `TableColumnResizer` in each `TableHead`. `'content'` — the columns still fit
     * their content. An array — one width in pixels per column, and only these decide the widths from then on, so a
     * cell can be narrower than what it holds. The table's width is their sum. Pass the array as the widths change.
     */
    columnWidths?: 'content' | number[]
    /** Classes for the inner `<table>`. Size/scroll go on the container via `className`. */
    tableClassName?: string
    /** Ref to the scrolling viewport — for scroll-to-row, virtualization, IntersectionObservers, etc. */
    viewportRef?: React.Ref<HTMLDivElement>
    /** Ref to a marker after the table, inside the viewport. Observe it to load more rows near the end. */
    viewportEndRef?: React.Ref<HTMLDivElement>
}

// The forwarded ref points at the `<table>` element (consistent with `...props`,
// which also land there). The scroll container is reached via `viewportRef`.
const Table = React.forwardRef<HTMLTableElement, TableProps>(function Table(
    {
        className,
        tableClassName,
        stickyHeader = false,
        fullWidth = false,
        size = 'default',
        columnWidths,
        viewportRef,
        viewportEndRef,
        style,
        children,
        ...props
    },
    ref
) {
    const rootRef = React.useRef<HTMLDivElement | null>(null)
    const innerViewportRef = React.useRef<HTMLDivElement | null>(null)
    useScrollEdges(rootRef, innerViewportRef)
    const setViewport = React.useCallback(
        (node: HTMLDivElement | null): void => setRefs(node, innerViewportRef, viewportRef),
        [viewportRef]
    )
    const widths = Array.isArray(columnWidths) ? columnWidths : null
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
            <div ref={setViewport} data-slot="table-viewport" className="quill-table__viewport">
                <table
                    ref={ref}
                    data-slot="table"
                    data-sticky-header={stickyHeader ? '' : undefined}
                    data-full-width={fullWidth ? '' : undefined}
                    data-size={size}
                    data-resizable={columnWidths ? '' : undefined}
                    data-layout={widths ? 'fixed' : undefined}
                    className={cn('quill-table', tableClassName)}
                    style={
                        widths
                            ? {
                                  ...style,
                                  // A full-width table fills its container, and only grows past it.
                                  ...(fullWidth ? {} : { width: sumWidths(widths) }),
                                  minWidth: fullWidth ? sumWidths(widths) : 0,
                              }
                            : style
                    }
                    {...props}
                >
                    {/* In the DOM from the first render: inserting it beside the rows at the first drag restyles them all. */}
                    {columnWidths ? (
                        <colgroup>
                            {widths?.map((width, index) => (
                                <col key={index} style={{ width }} />
                            ))}
                            {widths && fullWidth ? <col /> : null}
                        </colgroup>
                    ) : null}
                    {children}
                </table>
                {viewportEndRef ? <div ref={viewportEndRef} aria-hidden /> : null}
            </div>
        </div>
    )
})

const TableHeader = React.forwardRef<HTMLTableSectionElement, React.ComponentProps<'thead'>>(function TableHeader(
    { className, ...props },
    ref
) {
    return <thead ref={ref} data-slot="table-header" className={cn('quill-table__header', className)} {...props} />
})

const TableBody = React.forwardRef<HTMLTableSectionElement, React.ComponentProps<'tbody'>>(function TableBody(
    { className, ...props },
    ref
) {
    return <tbody ref={ref} data-slot="table-body" className={cn('quill-table__body', className)} {...props} />
})

const TableFooter = React.forwardRef<HTMLTableSectionElement, React.ComponentProps<'tfoot'>>(function TableFooter(
    { className, ...props },
    ref
) {
    return <tfoot ref={ref} data-slot="table-footer" className={cn('quill-table__footer', className)} {...props} />
})

const TableRow = React.forwardRef<HTMLTableRowElement, React.ComponentProps<'tr'>>(function TableRow(
    { className, ...props },
    ref
) {
    return <tr ref={ref} data-slot="table-row" className={cn('quill-table__row', className)} {...props} />
})

const TableHead = React.forwardRef<HTMLTableCellElement, React.ComponentProps<'th'> & { sticky?: Sticky } & CellLayout>(
    // `scope="col"` by default (the common case); override to "row" for row headers.
    function TableHead({ className, sticky, align, valign, expand, filler, scope = 'col', ...props }, ref) {
        return (
            <th
                ref={ref}
                data-slot="table-head"
                data-sticky={sticky}
                data-align={align}
                data-valign={valign}
                data-expand={expand ? '' : undefined}
                data-filler={filler ? '' : undefined}
                role={filler ? 'presentation' : undefined}
                scope={scope}
                className={cn('quill-table__head', className)}
                {...props}
            />
        )
    }
)

const TableCell = React.forwardRef<HTMLTableCellElement, React.ComponentProps<'td'> & { sticky?: Sticky } & CellLayout>(
    function TableCell({ className, sticky, align, valign, expand, filler, ...props }, ref) {
        return (
            <td
                ref={ref}
                data-slot="table-cell"
                data-sticky={sticky}
                data-align={align}
                data-valign={valign}
                data-expand={expand ? '' : undefined}
                data-filler={filler ? '' : undefined}
                role={filler ? 'presentation' : undefined}
                className={cn('quill-table__cell', className)}
                {...props}
            />
        )
    }
)

// Full-span empty state. Renders its own tbody + row + cell so it drops in
// alongside TableHeader where a TableBody would go. `colSpan` defaults huge and
// browsers clamp it to the real column count, so callers rarely set it. The cell
// stretches to the table's body height (give the Table a height to fill it) and
// centers its content — drop in `<Empty>` or plain text, no `h-full` needed.
const TableEmpty = React.forwardRef<HTMLTableCellElement, React.ComponentProps<'td'>>(function TableEmpty(
    { className, colSpan = 1000, children, ...props },
    ref
) {
    return (
        <tbody data-slot="table-empty">
            <tr>
                <td ref={ref} colSpan={colSpan} className={cn('quill-table__empty', className)} {...props}>
                    <div className="quill-table__empty-inner">{children}</div>
                </td>
            </tr>
        </tbody>
    )
})

const TableCaption = React.forwardRef<HTMLTableCaptionElement, React.ComponentProps<'caption'>>(function TableCaption(
    { className, ...props },
    ref
) {
    return <caption ref={ref} data-slot="table-caption" className={cn('quill-table__caption', className)} {...props} />
})

Table.displayName = 'Table'
TableHeader.displayName = 'TableHeader'
TableBody.displayName = 'TableBody'
TableFooter.displayName = 'TableFooter'
TableRow.displayName = 'TableRow'
TableHead.displayName = 'TableHead'
TableCell.displayName = 'TableCell'
TableEmpty.displayName = 'TableEmpty'
TableCaption.displayName = 'TableCaption'

export {
    Table,
    TableHeader,
    TableBody,
    TableFooter,
    TableHead,
    TableRow,
    TableCell,
    TableEmpty,
    TableCaption,
    previewTableColumnWidth,
}
