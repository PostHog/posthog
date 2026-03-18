import { useLayoutEffect, useRef } from 'react'

interface UseColumnWidthSyncParams {
    /** Ref to the breakdown row in the parent table */
    parentRowRef: React.RefObject<HTMLTableRowElement>
    /** Ref to the nested breakdown table */
    nestedTableRef: React.RefObject<HTMLTableElement>
}

// Constants for table structure validation
const BASELINE_ROW_CELL_COUNT = 7
const VARIANT_ROW_CELL_COUNT = 5
const EXPECTED_COLUMN_COUNT = 7
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
 * Measure column widths from a parent table's first data row
 */
const measureColumnWidths = (parentTable: HTMLTableElement): number[] => {
    // Get the first data row from the parent table (not the header, not the breakdown row)
    const firstDataRow = parentTable.querySelector('tbody tr:not([data-breakdown-row])') as HTMLTableRowElement
    if (!firstDataRow) {
        throw new Error('No data row found in parent table')
    }

    // Measure each cell's actual width (offsetWidth includes borders and padding)
    const cells = Array.from(firstDataRow.querySelectorAll('td'))

    // Validate we have the expected number of columns
    if (cells.length !== EXPECTED_COLUMN_COUNT) {
        console.warn(
            `[useColumnWidthSync] Unexpected parent table structure: expected ${EXPECTED_COLUMN_COUNT} columns, got ${cells.length}`
        )
        throw new Error('Unexpected column count')
    }

    const widths = cells.map((cell) => {
        const width = (cell as HTMLElement).offsetWidth
        if (width <= 0) {
            throw new Error('Measured column width is invalid (zero or negative)')
        }
        return width
    })

    return widths
}

/**
 * Clear inline width styles from nested table rows
 */
const clearRowStyles = (rows: NodeListOf<Element>): void => {
    rows.forEach((row) => {
        const cells = Array.from(row.querySelectorAll('td'))
        cells.forEach((cell) => {
            const cellElement = cell as HTMLElement
            cellElement.style.width = ''
            cellElement.style.minWidth = ''
            cellElement.style.maxWidth = ''
        })
    })
}

/**
 * Apply measured widths to nested table rows
 */
const applyWidthsToRows = (rows: NodeListOf<Element>, widths: number[]): void => {
    // Validate column widths array
    if (widths.length !== EXPECTED_COLUMN_COUNT) {
        console.warn(
            `[useColumnWidthSync] Column widths array has unexpected length: expected ${EXPECTED_COLUMN_COUNT}, got ${widths.length}`
        )
        return
    }

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

                // Measure column widths from parent table
                const widths = measureColumnWidths(parentTable)

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

        // Debounced resize handler - clear styles first to allow natural reflow
        const handleResize = (): void => {
            if (resizeTimeoutRef.current) {
                clearTimeout(resizeTimeoutRef.current)
            }
            resizeTimeoutRef.current = setTimeout(() => {
                // Clear existing styles to allow parent table to reflow naturally
                if (nestedTableRef.current) {
                    const rows = nestedTableRef.current.querySelectorAll('tbody tr')
                    clearRowStyles(rows)
                }
                // Small delay to let DOM reflow, then remeasure
                setTimeout(measureAndApplyWidths, 10)
            }, 150)
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
