// Pure column-layout helpers used by LemonTable internals. Kept separate from
// columnUtils.tsx, whose column factories render TZLabel/ProfilePicture and would
// otherwise drag that graph (including eventUsageLogic and the taxonomy JSON) into
// every bundle that renders a LemonTable.
import { LemonTableColumn } from './types'

export const DEFAULT_COLUMN_WIDTH = 120

interface PinnedColumnInfo {
    isSticky: boolean
    leftPosition: number
}

/**
 * Get the pinned column info
 * @param columnKey - The key of the column
 * @param stickyColumns - The pinned columns
 * @param stickyColumnWidths - The widths of the pinned columns
 * @param allColumns - All the columns
 * @returns The pinned column info
 * example:
 * getStickyColumnInfo(
 *     'source',
 *     ['source', 'campaign'],
 *     [100, 200],
 *     [
 *         { key: 'campaign', dataIndex: 'campaign' },
 *         { key: 'source', dataIndex: 'source' },
 *     ]
 * ) -> {
 *     isSticky: true,
 *     leftPosition: 100
 * }
 */
export function getStickyColumnInfo<T extends Record<string, any>>(
    columnKey: string,
    stickyColumns: string[] | undefined,
    stickyColumnWidths: number[] | undefined,
    allColumns: LemonTableColumn<T, any>[] | undefined
): PinnedColumnInfo {
    if (!stickyColumns?.length) {
        return { isSticky: false, leftPosition: 0 }
    }

    const isSticky = stickyColumns.includes(columnKey)

    if (!isSticky || !allColumns) {
        return { isSticky, leftPosition: 0 }
    }

    const columnPositionMap = new Map<string, number>()
    allColumns.forEach((col, index) => {
        const key = col.key ?? col.dataIndex
        if (key) {
            columnPositionMap.set(key, index)
        }
    })

    const columnIndex = columnPositionMap.get(columnKey) ?? -1

    // Calculate left position for pinned column
    let leftPosition = 0
    if (stickyColumnWidths) {
        for (let i = 0; i < stickyColumns.length; i++) {
            const key = stickyColumns[i]
            const keyIndex = columnPositionMap.get(key) ?? -1
            if (keyIndex >= 0 && keyIndex < columnIndex) {
                const width = stickyColumnWidths[i]
                leftPosition += width && width > 0 ? width : DEFAULT_COLUMN_WIDTH
            }
        }
    }

    return { isSticky, leftPosition }
}

/**
 * Determine the column's key, using `dataIndex` as fallback.
 * If `obligationReason` is specified, will throw an error if the key can't be determined.
 */
export function determineColumnKey(column: LemonTableColumn<any, any>, obligationReason: string): string
export function determineColumnKey(column: LemonTableColumn<any, any>, obligationReason?: undefined): string | null
export function determineColumnKey(column: LemonTableColumn<any, any>, obligationReason?: string): string | null {
    const columnKey = column.key || column.dataIndex
    if (obligationReason && columnKey == null) {
        // == is intentional to catch undefined too
        throw new Error(`Column \`key\` or \`dataIndex\` must be defined for ${obligationReason}`)
    }
    return columnKey
}
