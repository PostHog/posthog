import type {
    BookActivityPerson,
    BookActivityPersonFirstUse,
    BookActivityMatrixResult,
    BookActivityPeopleResult,
    BookActivityFirstsResult,
    HogQLQueryResponse,
    AccountsTableQueryResponse,
    DateRange,
    BookActivityInterval,
} from '~/queries/schema/schema-general'

import type { DotMatrixTileSource } from '../Accounts/dotMatrixTileConfig'
export type ProductUsageSource =
    | Exclude<DotMatrixTileSource, { kind: 'usage_metrics' | 'product_usage' }>
    | { kind: 'product_usage' }
export type ProductUsageZoom = 'count' | 'products' | 'users'
export interface ProductUsageLoadResult {
    accounts: AccountsTableQueryResponse
    matrix: BookActivityMatrixResult | null
    hogql: HogQLQueryResponse | null
    source: ProductUsageSource
    dateRange?: DateRange
    interval?: BookActivityInterval
}
export interface ProductUsageDetails {
    people: BookActivityPeopleResult | null
    firsts: BookActivityFirstsResult | null
}
export interface ProductUsageTableRow {
    key: string
    accountId: string
    label: string
    productKey?: string
}
export function productUsageRows(
    result: BookActivityMatrixResult,
    selected: string[],
    zoom: ProductUsageZoom
): ProductUsageTableRow[] {
    const usedByAccount = new Map<string, Set<string>>()
    for (const cell of result.data) {
        if (cell.users > 0) {
            const used = usedByAccount.get(cell.row) ?? new Set<string>()
            used.add(cell.series)
            usedByAccount.set(cell.row, used)
        }
    }
    return result.rows.flatMap((row) => {
        const account: ProductUsageTableRow = { key: row.key, accountId: row.key, label: row.label }
        if (zoom !== 'users') {
            return [account]
        }
        const used = usedByAccount.get(row.key) ?? new Set<string>()
        return [
            account,
            ...result.series
                .filter((series) => used.has(series.key) && (!selected.length || selected.includes(series.key)))
                .map((series) => ({
                    key: JSON.stringify([row.key, series.key]),
                    accountId: row.key,
                    label: series.label,
                    productKey: series.key,
                })),
        ]
    })
}
export function productUsageCellKey(accountId: string, column: string, productKey?: string): string {
    return JSON.stringify([accountId, column, productKey ?? null])
}

export function indexProductUsageCounts(result: BookActivityMatrixResult, selected: string[]): Map<string, number> {
    const counts = new Map<string, number>()
    const mask = result.series.reduce(
        (mask, series, index) => (selected.includes(series.key) ? mask | (2 ** index) : mask),
        0
    )
    for (const cell of selected.length ? result.combinations : result.data) {
        const value = 'mask' in cell ? ((cell.mask & mask) !== 0 ? cell.users : 0) : cell.users > 0 ? 1 : 0
        const key = productUsageCellKey(cell.row, cell.column)
        counts.set(key, (counts.get(key) ?? 0) + value)
    }
    return counts
}

export function productUsageCount(
    result: BookActivityMatrixResult,
    accountId: string,
    column: string,
    selected: string[]
): number {
    return indexProductUsageCounts(result, selected).get(productUsageCellKey(accountId, column)) ?? 0
}

export function indexProductUsagePeople(people: BookActivityPerson[]): Map<string, BookActivityPerson[]> {
    const indexed = new Map<string, BookActivityPerson[]>()
    for (const person of people) {
        const key = productUsageCellKey(person.row, person.column, person.series)
        const cell = indexed.get(key) ?? []
        cell.push(person)
        indexed.set(key, cell)
    }
    return indexed
}

export function indexProductUsageFirsts(
    firsts: BookActivityPersonFirstUse[]
): Map<string, BookActivityPersonFirstUse[]> {
    const indexed = new Map<string, BookActivityPersonFirstUse[]>()
    for (const first of firsts) {
        const key = JSON.stringify([first.row, first.series])
        const product = indexed.get(key) ?? []
        product.push(first)
        indexed.set(key, product)
    }
    return indexed
}
