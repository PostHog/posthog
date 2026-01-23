import { useCallback, useLayoutEffect, useRef } from 'react'

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
export function useColumnWidthSync(
    { parentRowRef, nestedTableRef }: UseColumnWidthSyncParams,
    deps: React.DependencyList = []
): void {
    const resizeTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const mutationTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const previousWidthsRef = useRef<number[]>([])
    const previousNestedTableRef = useRef<HTMLTableElement | null>(null)

    /**
     * we check if the widths have actually changed
     * we use useCallback to provide a stable reference to the function
     */
    const widthsHaveChanged = useCallback((newWidths: number[]): boolean => {
        const prev = previousWidthsRef.current
        if (prev.length !== newWidths.length) {
            return true
        }
        // Compare with small tolerance for sub-pixel rendering differences
        const tolerance = 0.5
        return newWidths.some((width, i) => Math.abs(width - prev[i]) > tolerance)
    }, [])

    /**
     * we get the parent column index for the nested table
     * we use useCallback to provide a stable reference to the function
     */
    const getParentColumnIndex = useCallback((cellIndex: number, cellCount: number): number | null => {
        if (cellCount === BASELINE_ROW_CELL_COUNT) {
            // Baseline row: maps 1:1 with parent columns
            return cellIndex
        } else if (cellCount === VARIANT_ROW_CELL_COUNT) {
            // Variant row: skip breakdown label (col 0) and details (col 5)
            if (cellIndex < 4) {
                return cellIndex + 1 // Columns 1-4
            }
            return cellIndex + 2 // Column 6 (chart)
        }
        return null
    }, [])

    /**
     * we apply the widths to the nested table after the parent table has been measured
     *
     * we use useCallback to provide a stable reference to the function
     */
    const applyWidthsToNestedTable = useCallback(
        (widths: number[]): void => {
            if (!nestedTableRef.current || widths.length === 0) {
                return
            }

            // Validate column widths array
            if (widths.length !== EXPECTED_COLUMN_COUNT) {
                console.warn(
                    `[useColumnWidthSync] Column widths array has unexpected length: expected ${EXPECTED_COLUMN_COUNT}, got ${widths.length}`
                )
                return
            }

            try {
                const rows = nestedTableRef.current.querySelectorAll('tbody tr')

                rows.forEach((row) => {
                    const cells = Array.from(row.querySelectorAll('td'))
                    const cellCount = cells.length

                    cells.forEach((cell, cellIndex) => {
                        // Use memoized column mapping function
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
            } catch (error) {
                console.error('[useColumnWidthSync] Error applying column widths:', error)
                // Fail silently - table will render with default widths
            }
        },
        [nestedTableRef, getParentColumnIndex]
    )

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
                const parentTable = parentRowRef.current?.closest('table')
                if (!parentTable) {
                    return
                }

                // Get the first data row from the parent table (not the header, not the breakdown row)
                const firstDataRow = parentTable.querySelector(
                    'tbody tr:not([data-breakdown-row])'
                ) as HTMLTableRowElement
                if (!firstDataRow) {
                    return
                }

                // Measure each cell's actual width (offsetWidth includes borders and padding)
                const cells = Array.from(firstDataRow.querySelectorAll('td'))

                // Validate we have the expected number of columns
                if (cells.length !== EXPECTED_COLUMN_COUNT) {
                    console.warn(
                        `[useColumnWidthSync] Unexpected parent table structure: expected ${EXPECTED_COLUMN_COUNT} columns, got ${cells.length}`
                    )
                    return
                }

                const widths = cells.map((cell) => {
                    const width = (cell as HTMLElement).offsetWidth
                    if (width <= 0) {
                        throw new Error('Measured column width is invalid (zero or negative)')
                    }
                    return width
                })

                // Check if nested table is new (different instance from last time)
                const isNewNestedTable = nestedTableRef.current !== previousNestedTableRef.current
                previousNestedTableRef.current = nestedTableRef.current

                // Check if widths have changed
                const widthsChanged = widthsHaveChanged(widths)

                // Store the new widths
                previousWidthsRef.current = widths

                // Apply widths if they changed OR if nested table is new (reopened collapse)
                if (widthsChanged || isNewNestedTable) {
                    applyWidthsToNestedTable(widths)
                }
            } catch (error) {
                console.error('[useColumnWidthSync] Error measuring column widths:', error)
                // Don't show toast to user - this is a visual layout issue, not a critical error
                // Fail silently and let the table render with default widths
            }
        }

        // Debounced resize handler
        const handleResize = (): void => {
            if (resizeTimeoutRef.current) {
                clearTimeout(resizeTimeoutRef.current)
            }
            resizeTimeoutRef.current = setTimeout(measureAndApplyWidths, 150)
        }

        // Initial measurement with a small delay to allow DOM to settle
        const timeoutId = setTimeout(measureAndApplyWidths, 0)
        window.addEventListener('resize', handleResize)

        // Use MutationObserver to detect when nested table appears (with debouncing)
        const observer = new MutationObserver(() => {
            if (nestedTableRef.current) {
                // Debounce mutation observations to avoid excessive measurements
                if (mutationTimeoutRef.current) {
                    clearTimeout(mutationTimeoutRef.current)
                }
                mutationTimeoutRef.current = setTimeout(measureAndApplyWidths, 50)
            }
        })

        if (parentRowRef.current) {
            observer.observe(parentRowRef.current, {
                childList: true,
                subtree: true,
            })
        }

        return () => {
            clearTimeout(timeoutId)
            if (resizeTimeoutRef.current) {
                clearTimeout(resizeTimeoutRef.current)
            }
            if (mutationTimeoutRef.current) {
                clearTimeout(mutationTimeoutRef.current)
            }
            window.removeEventListener('resize', handleResize)
            observer.disconnect()
        }
    }, [...deps, widthsHaveChanged, applyWidthsToNestedTable])
}
