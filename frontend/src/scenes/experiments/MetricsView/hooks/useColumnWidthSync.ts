import { useLayoutEffect, useRef } from 'react'

interface UseColumnWidthSyncParams {
    /** Ref to the breakdown row in the parent table */
    parentRowRef: React.RefObject<HTMLTableRowElement>
    /** Ref to the nested breakdown table */
    nestedTableRef: React.RefObject<HTMLTableElement>
}

// Constants for mapping nested breakdown cells back to their parent columns
const BASELINE_ROW_CELL_COUNT = 7
const VARIANT_ROW_CELL_COUNT = 5
const WIDTH_COMPARISON_TOLERANCE = 0.5 // Tolerance for sub-pixel rendering differences

/**
 * Check if widths have actually changed between measurements
 */
const widthsHaveChanged = (newWidths: number[], previousWidths: number[]): boolean => {
    if (previousWidths.length !== newWidths.length) {
        return true
    }
    return newWidths.some((width, i) => Math.abs(width - previousWidths[i]) > WIDTH_COMPARISON_TOLERANCE)
}

/**
 * Get the parent column index for a cell in the nested breakdown table
 */
const getParentColumnIndex = (cellIndex: number, cellCount: number): number | null => {
    if (cellCount === BASELINE_ROW_CELL_COUNT) {
        // Baseline row: maps 1:1 with parent columns
        return cellIndex
    }

    if (cellCount === VARIANT_ROW_CELL_COUNT) {
        // Variant row: skip breakdown label (col 0) and details (col 5)
        if (cellIndex < 4) {
            return cellIndex + 1 // Columns 1-4
        }
        return cellIndex + 2 // Column 6 (chart)
    }

    return null
}

/**
 * Measure column widths from a parent table's first data row.
 *
 * Returns null (rather than throwing) when the measurement is not usable yet — no data row,
 * no cells, or a cell that measures 0 mid-transition. Callers must treat null as "keep the
 * widths that are already applied" so a failed remeasure never blanks the breakdown cells.
 */
const measureColumnWidths = (parentTable: HTMLTableElement): number[] | null => {
    // Get the first data row from the parent table (not the header, not the breakdown row)
    const firstDataRow = parentTable.querySelector('tbody tr:not([data-breakdown-row])') as HTMLTableRowElement | null
    if (!firstDataRow) {
        return null
    }

    // Measure each cell's actual width (offsetWidth includes borders and padding).
    // Measure whatever columns exist rather than asserting a fixed count, so an added or
    // removed column doesn't silently blank the table.
    const cells = Array.from(firstDataRow.querySelectorAll('td'))
    if (cells.length === 0) {
        return null
    }

    const widths: number[] = []
    for (const cell of cells) {
        const width = (cell as HTMLElement).offsetWidth
        if (width <= 0) {
            // Mid-transition measurement; bail out and keep the previously applied widths.
            return null
        }
        widths.push(width)
    }

    return widths
}

/**
 * Apply measured widths to nested table rows
 */
const applyWidthsToRows = (rows: NodeListOf<Element>, widths: number[]): void => {
    rows.forEach((row) => {
        const cells = Array.from(row.querySelectorAll('td'))
        const cellCount = cells.length

        cells.forEach((cell, cellIndex) => {
            // Get parent column index for this cell
            const parentColumnIndex = getParentColumnIndex(cellIndex, cellCount)

            if (parentColumnIndex === null) {
                // Unknown structure - log warning once per unique cell count
                console.warn(
                    `[useColumnWidthSync] Unexpected row structure: expected ${BASELINE_ROW_CELL_COUNT} or ${VARIANT_ROW_CELL_COUNT} cells, got ${cellCount}`
                )
                return
            }

            // Validate parent column index is within bounds
            if (parentColumnIndex < 0 || parentColumnIndex >= widths.length) {
                console.warn(
                    `[useColumnWidthSync] Parent column index out of bounds: ${parentColumnIndex} (max: ${widths.length - 1})`
                )
                return
            }

            const width = widths[parentColumnIndex]
            if (width && width > 0) {
                const cellElement = cell as HTMLElement
                // Batch style updates to minimize reflows
                cellElement.style.cssText += `width: ${width}px; min-width: ${width}px; max-width: ${width}px; box-sizing: border-box;`
            }
        })
    })
}

/**
 * Custom hook to sync column widths between a parent table and a nested breakdown table.
 *
 * This hook measures the actual rendered widths of columns in the parent table and applies
 * them to the nested table to ensure perfect alignment, regardless of content differences.
 *
 * @param params - Object containing parentRowRef and nestedTableRef
 * @param deps - Dependency array that triggers re-measurement (like useEffect)
 *
 * @example
 * useColumnWidthSync({
 *   parentRowRef: mainTableRef,
 *   nestedTableRef: breakdownTableRef
 * }, [breakdownResults, axisRange])
 */
export const useColumnWidthSync = (
    { parentRowRef, nestedTableRef }: UseColumnWidthSyncParams,
    deps: React.DependencyList = []
): void => {
    const resizeTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const previousWidthsRef = useRef<number[]>([])
    const previousNestedTableRef = useRef<HTMLTableElement | null>(null)

    // Single effect to measure and apply column widths
    useLayoutEffect(() => {
        if (!parentRowRef.current) {
            return
        }

        const measureAndApplyWidths = (): void => {
            try {
                // Check if nested table exists (it might not be rendered yet if collapse is closed)
                if (!nestedTableRef.current) {
                    return
                }

                // Find the parent table by traversing up from the breakdown row
                const parentTable = parentRowRef.current?.closest('table') as HTMLTableElement
                if (!parentTable) {
                    return
                }

                // Measure column widths from parent table. A null result means the parent
                // isn't in a measurable state yet; keep any widths already applied rather
                // than clearing them, so the breakdown cells never collapse.
                const widths = measureColumnWidths(parentTable)
                if (!widths) {
                    return
                }

                // Check if nested table is new (different instance from last time)
                const isNewNestedTable = nestedTableRef.current !== previousNestedTableRef.current
                previousNestedTableRef.current = nestedTableRef.current

                // Check if widths have changed
                const widthsChanged = widthsHaveChanged(widths, previousWidthsRef.current)

                // Store the new widths
                previousWidthsRef.current = widths

                // Apply widths if they changed OR if nested table is new (reopened collapse)
                if (widthsChanged || isNewNestedTable) {
                    const rows = nestedTableRef.current.querySelectorAll('tbody tr')
                    applyWidthsToRows(rows, widths)
                }
            } catch (error) {
                console.error('[useColumnWidthSync] Error measuring column widths:', error)
                // Don't show toast to user - this is a visual layout issue, not a critical error
                // Fail silently and let the table render with default widths
            }
        }

        // Debounced resize handler. The parent table's column widths are driven by its own
        // data rows and reflow on resize independently of the nested table's inline widths,
        // so we can remeasure and overwrite in place. We deliberately do NOT clear the
        // existing widths first: if the remeasure fails, the cells keep their last-known
        // widths instead of staying collapsed.
        const handleResize = (): void => {
            if (resizeTimeoutRef.current) {
                clearTimeout(resizeTimeoutRef.current)
            }
            resizeTimeoutRef.current = setTimeout(measureAndApplyWidths, 150)
        }

        // Initial measurement with a small delay to allow DOM to settle
        const timeoutId = setTimeout(measureAndApplyWidths, 0)
        window.addEventListener('resize', handleResize)

        return () => {
            clearTimeout(timeoutId)
            if (resizeTimeoutRef.current) {
                clearTimeout(resizeTimeoutRef.current)
            }
            window.removeEventListener('resize', handleResize)
        }
    }, deps)
}
