import type { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'

import type { AccountSortOrder } from './accountsLogic'

// `0` and `false` are real values, not empty
function isEmptyCell(value: unknown): boolean {
    if (value === null || value === undefined || value === '') {
        return true
    }
    return Array.isArray(value) && value.length === 0
}

// The name column arrives as a { name, external_id, id } tuple, relationship/tag columns as arrays
function getSortKey(value: unknown): number | string {
    if (typeof value === 'number') {
        return value
    }
    if (Array.isArray(value)) {
        return value.join(',')
    }
    if (value && typeof value === 'object') {
        const name = (value as { name?: unknown }).name
        return typeof name === 'string' ? name : String(value)
    }
    return String(value)
}

function compareNonEmpty(a: unknown, b: unknown): number {
    const ka = getSortKey(a)
    const kb = getSortKey(b)
    if (typeof ka === 'number' && typeof kb === 'number') {
        return ka < kb ? -1 : ka > kb ? 1 : 0
    }
    // numeric-aware collation so "2" sorts before "10"
    return String(ka).localeCompare(String(kb), undefined, { numeric: true, sensitivity: 'base' })
}

function getCellAt(row: DataTableRow, index: number): unknown {
    return Array.isArray(row.result) ? row.result[index] : undefined
}

export function sortAccountRows(
    rows: DataTableRow[],
    sortOrder: AccountSortOrder,
    visibleColumnNames: string[]
): DataTableRow[] {
    if (!sortOrder) {
        return rows
    }
    const index = visibleColumnNames.indexOf(sortOrder.column)
    if (index < 0) {
        return rows
    }
    const direction = sortOrder.direction === 'desc' ? -1 : 1
    return [...rows].sort((a, b) => {
        const av = getCellAt(a, index)
        const bv = getCellAt(b, index)
        const aEmpty = isEmptyCell(av)
        const bEmpty = isEmptyCell(bv)
        if (aEmpty || bEmpty) {
            // empty cells sort last in both directions
            return aEmpty === bEmpty ? 0 : aEmpty ? 1 : -1
        }
        return compareNonEmpty(av, bv) * direction
    })
}
