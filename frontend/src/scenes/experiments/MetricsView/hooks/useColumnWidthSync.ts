import { useCallback, useLayoutEffect, useRef, useState } from 'react'

interface UseColumnWidthSyncParams {
    /** Ref to the breakdown row in the parent table */
    parentRowRef: React.RefObject<HTMLTableRowElement>
    /** Ref to the nested breakdown table */
    nestedTableRef: React.RefObject<HTMLTableElement>
    /** Dependencies to trigger re-measurement */
    deps?: any[]
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
 * @param parentRowRef - Reference to the breakdown row in the parent table
 * @param nestedTableRef - Reference to the nested table that needs width syncing
 * @param deps - Optional dependencies that trigger re-measurement
 */
export function useColumnWidthSync({ parentRowRef, nestedTableRef, deps = [] }: UseColumnWidthSyncParams): void {
    const [columnWidths, setColumnWidths] = useState<number[]>([])
    const resizeTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const mutationTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const previousWidthsRef = useRef<number[]>([])

    // Memoized helper to check if widths have actually changed
    const widthsHaveChanged = useCallback((newWidths: number[]): boolean => {
        const prev = previousWidthsRef.current
        if (prev.length !== newWidths.length) {
            return true
        }
        // Compare with small tolerance for sub-pixel rendering differences
        const tolerance = 0.5
        return newWidths.some((width, i) => Math.abs(width - prev[i]) > tolerance)
    }, [])

    // Memoized column mapping function
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

    // Measure parent table column widths
    useLayoutEffect(() => {
        if (!parentRowRef.current) {
            return
        }

        const measureColumnWidths = (): void => {
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

                // Only update state if widths have actually changed (prevent unnecessary re-renders)
                if (widthsHaveChanged(widths)) {
                    previousWidthsRef.current = widths
                    setColumnWidths(widths)
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
            resizeTimeoutRef.current = setTimeout(measureColumnWidths, 150)
        }

        // Initial measurement with a small delay to allow DOM to settle
        const timeoutId = setTimeout(measureColumnWidths, 0)
        window.addEventListener('resize', handleResize)

        // Use MutationObserver to detect when nested table appears (with debouncing)
        const observer = new MutationObserver(() => {
            if (nestedTableRef.current) {
                // Debounce mutation observations to avoid excessive measurements
                if (mutationTimeoutRef.current) {
                    clearTimeout(mutationTimeoutRef.current)
                }
                mutationTimeoutRef.current = setTimeout(measureColumnWidths, 50)
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
    }, [...deps, widthsHaveChanged])

    // Apply measured widths to nested table columns
    useLayoutEffect(() => {
        if (!nestedTableRef.current || columnWidths.length === 0) {
            return
        }

        // Validate column widths array
        if (columnWidths.length !== EXPECTED_COLUMN_COUNT) {
            console.warn(
                `[useColumnWidthSync] Column widths array has unexpected length: expected ${EXPECTED_COLUMN_COUNT}, got ${columnWidths.length}`
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
                    if (parentColumnIndex < 0 || parentColumnIndex >= columnWidths.length) {
                        console.warn(
                            `[useColumnWidthSync] Parent column index out of bounds: ${parentColumnIndex} (max: ${columnWidths.length - 1})`
                        )
                        return
                    }

                    const width = columnWidths[parentColumnIndex]
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
    }, [columnWidths, nestedTableRef, getParentColumnIndex])
}
