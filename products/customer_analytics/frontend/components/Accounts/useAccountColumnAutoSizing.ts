import { RefObject, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { objectsEqual } from 'lib/utils/objects'

import { QueryContextColumn } from '~/queries/types'

function getContentWidths(table: HTMLTableElement, columnNames: string[]): Record<string, number> {
    const measurementTable = table.cloneNode(true) as HTMLTableElement
    measurementTable.removeAttribute('style')
    measurementTable.classList.remove('table-fixed')
    measurementTable.classList.add('fixed', 'invisible', 'pointer-events-none', 'table-auto', 'w-max!', 'min-w-0')
    measurementTable.inert = true
    measurementTable
        .querySelectorAll('colgroup, tfoot, .LemonTable__expansion, .LemonTable__loader-row')
        .forEach((element) => element.remove())
    measurementTable.querySelectorAll<HTMLElement>('th, td').forEach((cell) => {
        cell.style.maxWidth = 'none'
        cell.style.whiteSpace = 'nowrap'
    })
    table.parentElement?.appendChild(measurementTable)
    try {
        const widths: Record<string, number> = {}
        for (const header of measurementTable.querySelectorAll<HTMLTableCellElement>('thead th')) {
            const sortControl = header.querySelector<HTMLElement>('[data-attr^="accounts-table-sort-"]')
            const columnName = sortControl?.getAttribute('data-attr')?.slice('accounts-table-sort-'.length)
            if (columnName && columnNames.includes(columnName)) {
                widths[columnName] = Math.min(200, Math.max(80, Math.ceil(header.getBoundingClientRect().width)))
            }
        }
        return widths
    } finally {
        measurementTable.remove()
    }
}

export function useAccountColumnAutoSizing(
    columns: Record<string, QueryContextColumn>,
    response: unknown,
    loading: boolean
): {
    tableRef: RefObject<HTMLDivElement>
    columns: Record<string, QueryContextColumn>
    hasAutoSizedColumns: boolean
} {
    const tableRef = useRef<HTMLDivElement>(null)
    const [contentWidths, setContentWidths] = useState<Record<string, number>>({})

    useLayoutEffect(() => {
        const table = tableRef.current?.querySelector<HTMLTableElement>('.LemonTable__content > table')
        const columnNames = Object.keys(columns).filter((key) => columns[key].width === undefined)
        if (!table || loading || !response || columnNames.length === 0) {
            return
        }
        const widths = getContentWidths(table, columnNames)
        setContentWidths((previous) => (objectsEqual(previous, widths) ? previous : widths))
    }, [columns, response, loading])

    const sizedColumns = useMemo(
        () =>
            Object.fromEntries(
                Object.entries(columns).map(([key, column]) => [
                    key,
                    { ...column, width: column.width ?? contentWidths[key] },
                ])
            ),
        [columns, contentWidths]
    )

    return {
        tableRef,
        columns: sizedColumns,
        hasAutoSizedColumns: Object.keys(columns).some(
            (key) => columns[key].width === undefined && contentWidths[key] !== undefined
        ),
    }
}
