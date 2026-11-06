import { type ColumnSizingState, type Table } from '@tanstack/react-table'
import * as React from 'react'

/**
 * The widths for a `Table`'s `columnWidths`. The columns fit their content until the first resize, or until there are
 * saved widths to apply. Then every column is fixed, each at its saved width or else at the width it had on screen, so
 * that a resize changes the dragged column and no other. A change in the set of columns measures them again.
 */
export function useColumnWidths<TData>(
    table: Table<TData>,
    tableRef: React.RefObject<HTMLTableElement | null>,
    enabled: boolean
): {
    columnWidths: 'content' | number[] | undefined
    /** Fixes the columns at their widths on screen, if they still fit their content. */
    fixColumnWidths: () => void
    columnWidth: (columnId: string) => number | undefined
} {
    const leafColumns = table.getVisibleLeafColumns()
    const columnKey = leafColumns.map((column) => column.id).join()
    const [measured, setMeasured] = React.useState<{ columnKey: string; widths: ColumnSizingState } | null>(null)
    const measuredWidths = measured?.columnKey === columnKey ? measured.widths : null

    const fixColumnWidths = (): void => {
        if (measuredWidths) {
            return
        }
        const heads = tableRef.current?.querySelectorAll('thead tr:last-child th')
        setMeasured({
            columnKey,
            widths: Object.fromEntries(
                leafColumns.map((column, index) => [column.id, heads?.[index]?.getBoundingClientRect().width ?? 0])
            ),
        })
    }

    const sizing = table.getState().columnSizing
    const hasRows = table.getRowModel().rows.length > 0
    const hasSavedWidths = Object.keys(sizing).length > 0
    // Before paint, so that saved widths apply from the first frame. It waits for rows to measure the others against.
    React.useLayoutEffect(() => {
        if (enabled && hasRows && hasSavedWidths) {
            fixColumnWidths()
        }
    })

    if (!enabled) {
        return { columnWidths: undefined, fixColumnWidths, columnWidth: () => undefined }
    }
    if (!measuredWidths) {
        return { columnWidths: 'content', fixColumnWidths, columnWidth: () => undefined }
    }
    const widthOf = (id: string): number =>
        id in sizing ? (table.getColumn(id)?.getSize() ?? 0) : (measuredWidths[id] ?? 0)
    return {
        columnWidths: leafColumns.map((column) => widthOf(column.id)),
        fixColumnWidths,
        columnWidth: widthOf,
    }
}
