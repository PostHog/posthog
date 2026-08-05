import type { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'

import type { AccountSortOrder } from './accountsLogic'

// Client-side sort for the accounts list, applied while the whole matching set is
// loaded in the browser (`canSortClientSide`). Toggling a column header then reorders
// the already-loaded rows instead of refetching — sorting is instant, because the
// query carries no `orderBy` and stays semantically stable. When the list is
// paginated the query instead carries an `orderBy` and ClickHouse returns globally
// sorted rows, so this transformer is not applied. The backend's default order is
// created_at DESC; this reorders whatever has been loaded.

// A cell counts as empty (and always sorts last, in both directions) when it has no
// value to compare: null/undefined, the empty string, or an empty array (e.g. an
// unassigned relationship column). `0` and `false` are real values, not empty.
function isEmptyCell(value: unknown): boolean {
    if (value === null || value === undefined || value === '') {
        return true
    }
    return Array.isArray(value) && value.length === 0
}

// Reduce a raw cell to something comparable. The `name` column arrives as a
// `{ name, external_id, id }` tuple, relationship/tag columns as arrays; everything
// else is already a primitive (number, or a string — including numeric custom
// properties stored as strings).
function sortKey(value: unknown): number | string {
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

// Ascending comparison of two non-empty cells. Numbers compare numerically; anything
// else compares as a string with natural (numeric-aware, case-insensitive) collation,
// which also orders numeric strings ("2" before "10") correctly.
function compareNonEmpty(a: unknown, b: unknown): number {
    const ka = sortKey(a)
    const kb = sortKey(b)
    if (typeof ka === 'number' && typeof kb === 'number') {
        return ka < kb ? -1 : ka > kb ? 1 : 0
    }
    return String(ka).localeCompare(String(kb), undefined, { numeric: true, sensitivity: 'base' })
}

function cellAt(row: DataTableRow, index: number): unknown {
    return Array.isArray(row.result) ? row.result[index] : undefined
}

/**
 * Reorder the loaded table rows by the active sort. Returns the input untouched when
 * there is no sort, or when the sorted column isn't currently visible (its values
 * aren't in the row arrays). The sort is stable: rows with equal keys keep their
 * incoming (server default) order, and empty cells always sort last.
 */
export function sortAccountRows(
    rows: DataTableRow[],
    sortOrder: AccountSortOrder,
    visibleColumnNames: string[]
): DataTableRow[] {
    if (!sortOrder) {
        return rows
    }
    // Every column — including the name column — sorts by its visible name, which is
    // the position of its cell within each row's result array.
    const index = visibleColumnNames.indexOf(sortOrder.column)
    if (index < 0) {
        return rows
    }
    const direction = sortOrder.direction === 'desc' ? -1 : 1
    return rows
        .map((row, position) => ({ row, position }))
        .sort((a, b) => {
            const av = cellAt(a.row, index)
            const bv = cellAt(b.row, index)
            const aEmpty = isEmptyCell(av)
            const bEmpty = isEmptyCell(bv)
            if (aEmpty || bEmpty) {
                if (aEmpty && bEmpty) {
                    return a.position - b.position
                }
                return aEmpty ? 1 : -1
            }
            const cmp = compareNonEmpty(av, bv)
            return cmp !== 0 ? cmp * direction : a.position - b.position
        })
        .map(({ row }) => row)
}
