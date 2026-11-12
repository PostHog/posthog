import type { SortDirection } from './catalogTableRows'

export interface ColumnSort<Column extends string> {
    column: Column
    direction: SortDirection
}

export type SortValue = string | number | null

export type SortValueGetters<Item, Column extends string> = Record<Column, (item: Item) => SortValue>

function compareValues(left: string | number, right: string | number): number {
    return typeof left === 'string' && typeof right === 'string'
        ? left.localeCompare(right)
        : Number(left) - Number(right)
}

export function nextColumnSort<Column extends string>(
    current: ColumnSort<Column> | null,
    column: Column
): ColumnSort<Column> | null {
    if (current?.column !== column) {
        return { column, direction: 'asc' }
    }
    return current.direction === 'asc' ? { column, direction: 'desc' } : null
}

export function sortByColumn<Item, Column extends string>(
    items: Item[],
    sort: ColumnSort<Column> | null,
    getters: SortValueGetters<Item, Column>,
    tiebreakName: (item: Item) => string
): Item[] {
    if (!sort) {
        return items
    }
    const valueOf = getters[sort.column]
    const sign = sort.direction === 'asc' ? 1 : -1
    return [...items].sort((left, right) => {
        const leftValue = valueOf(left)
        const rightValue = valueOf(right)
        const tiebreak = tiebreakName(left).localeCompare(tiebreakName(right))
        if (leftValue === null || rightValue === null) {
            return Number(leftValue === null) - Number(rightValue === null) || tiebreak
        }
        return sign * compareValues(leftValue, rightValue) || tiebreak
    })
}

export function sortDirectionFor<Column extends string>(
    sort: ColumnSort<Column> | null,
    column: Column
): SortDirection | null {
    return sort?.column === column ? sort.direction : null
}
