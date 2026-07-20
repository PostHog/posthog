export interface PivotConfig {
    rowAliases: string[]
    columnAliases: string[]
    valueAliases: string[]
}

export type PivotCellValue = number | string | null

export interface PivotData {
    /** Distinct row-dimension tuples, in first-seen (i.e. ORDER BY) order */
    rowKeys: string[][]
    /** Distinct column-dimension labels in first-seen order; [''] when there are no column dimensions */
    columnKeys: string[]
    /** rowKey (joined) -> columnKey -> one value per valueAlias */
    cells: Record<string, Record<string, PivotCellValue[]>>
    duplicateCount: number
}

// NUL can't occur in rendered labels, so joined tuples can never collide ("a b"+"c" vs "a"+"b c")
const KEY_SEPARATOR = '\u0000'
export const NULL_DIMENSION_LABEL = '(null)'

export function pivotRowKey(tuple: string[]): string {
    return tuple.join(KEY_SEPARATOR)
}

function formatDimensionLabel(value: unknown): string {
    if (value === null || value === undefined || value === '') {
        return NULL_DIMENSION_LABEL
    }
    return String(value)
}

export function buildPivotData(
    rows: any[][],
    columnIndexByName: Record<string, number>,
    config: PivotConfig
): PivotData {
    const rowKeys: string[][] = []
    const columnKeys: string[] = []
    // Prototype-less: dimension labels are user data used as keys, so a `__proto__` label on a
    // plain object would write through to Object.prototype (prototype pollution)
    const cells: Record<string, Record<string, PivotCellValue[]>> = Object.create(null)
    let duplicateCount = 0

    const rowIndexes = config.rowAliases.map((alias) => columnIndexByName[alias])
    const columnIndexes = config.columnAliases.map((alias) => columnIndexByName[alias])
    const valueIndexes = config.valueAliases.map((alias) => columnIndexByName[alias])

    if ([...rowIndexes, ...columnIndexes, ...valueIndexes].some((index) => index === undefined)) {
        return { rowKeys, columnKeys, cells, duplicateCount }
    }

    const seenRowKeys = new Set<string>()
    const seenColumnKeys = new Set<string>()
    const seenCells = new Set<string>()

    for (const row of rows) {
        const rowTuple = rowIndexes.map((index) => formatDimensionLabel(row[index]))
        const rowKey = pivotRowKey(rowTuple)
        const columnKey = columnIndexes.map((index) => formatDimensionLabel(row[index])).join(' / ')

        if (!seenRowKeys.has(rowKey)) {
            seenRowKeys.add(rowKey)
            rowKeys.push(rowTuple)
        }
        if (!seenColumnKeys.has(columnKey)) {
            seenColumnKeys.add(columnKey)
            columnKeys.push(columnKey)
        }

        const cellKey = `${rowKey}${KEY_SEPARATOR}${KEY_SEPARATOR}${columnKey}`
        if (seenCells.has(cellKey)) {
            duplicateCount += 1
        }
        seenCells.add(cellKey)

        if (!cells[rowKey]) {
            cells[rowKey] = Object.create(null)
        }
        cells[rowKey][columnKey] = valueIndexes.map((index) => {
            const value = row[index]
            return value === undefined ? null : (value as PivotCellValue)
        })
    }

    return { rowKeys, columnKeys, cells, duplicateCount }
}
