import { TZLabel } from 'lib/components/TZLabel'
import { Dayjs, dayjs } from 'lib/dayjs'

import { UserBasicType } from '~/types'

import { LemonTag } from '../LemonTag'
import { ProfilePicture } from '../ProfilePicture'
import { LemonTableColumn } from './types'

export function atColumn<T extends Record<string, any>>(key: keyof T, title: string): LemonTableColumn<T, typeof key> {
    return {
        title: title,
        dataIndex: key,
        render: function RenderAt(created_at) {
            return created_at ? (
                <div className="whitespace-nowrap text-right">
                    <TZLabel time={created_at} />
                </div>
            ) : (
                <span className="text-secondary">—</span>
            )
        },
        align: 'right',
        sorter: (a, b) => dayjs(a[key] || 0).diff(b[key] || 0),
    }
}
export function createdAtColumn<T extends { created_at?: string | Dayjs | null }>(): LemonTableColumn<T, 'created_at'> {
    return atColumn('created_at', 'Created') as LemonTableColumn<T, 'created_at'>
}

export function updatedAtColumn<T extends { updated_at?: string | Dayjs | null }>(): LemonTableColumn<T, 'updated_at'> {
    return atColumn('updated_at', 'Updated') as LemonTableColumn<T, 'updated_at'>
}

export function createdByColumn<T extends { created_by?: UserBasicType | null }>(): LemonTableColumn<T, 'created_by'> {
    return {
        title: 'Created by',
        dataIndex: 'created_by',
        render: function Render(_: any, item) {
            const { created_by } = item
            return (
                <div className="flex flex-row items-center flex-nowrap">
                    {created_by && <ProfilePicture user={created_by} size="md" showName />}
                </div>
            )
        },
        sorter: (a, b) =>
            (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                b.created_by?.first_name || b.created_by?.email || ''
            ),
    }
}

export function statusColumn<T extends { enabled: boolean }>(): LemonTableColumn<T, 'enabled'> {
    return {
        title: 'Status',
        dataIndex: 'enabled',
        render: function Status(enabled) {
            return enabled ? (
                <LemonTag type="success" className="uppercase">
                    Enabled
                </LemonTag>
            ) : (
                <LemonTag type="default" className="uppercase">
                    Disabled
                </LemonTag>
            )
        },
        align: 'center',
        sorter: (a, b) => Number(b.enabled) - Number(a.enabled),
    }
}

export const DEFAULT_COLUMN_WIDTH = 120

interface PinnedColumnInfo {
    isPinned: boolean
    isLastPinned: boolean
    leftPosition: number
}

/**
 * Get the pinned column info
 * @param columnKey - The key of the column
 * @param pinnedColumns - The pinned columns
 * @param pinnedColumnWidths - The widths of the pinned columns
 * @param allColumns - The all columns
 * @returns The pinned column info
 * example:
 * getPinnedColumnInfo(
 *     'source',
 *     ['source', 'campaign'],
 *     [100, 200],
 *     [
 *         { key: 'campaign', dataIndex: 'campaign' },
 *         { key: 'source', dataIndex: 'source' },
 *     ]
 * ) -> {
 *     isPinned: true,
 *     isLastPinned: false,
 *     leftPosition: 100
 * }
 */
export function getPinnedColumnInfo<T extends Record<string, any>>(
    columnKey: string,
    pinnedColumns: string[] | undefined,
    pinnedColumnWidths: number[] | undefined,
    allColumns: LemonTableColumn<T, any>[] | undefined
): PinnedColumnInfo {
    if (!pinnedColumns?.length) {
        return { isPinned: false, isLastPinned: false, leftPosition: 0 }
    }

    const isPinned = pinnedColumns.includes(columnKey)

    // Find the last pinned column based on actual table positions
    let isLastPinned = false
    if (isPinned && allColumns) {
        const pinnedColumnPositions = pinnedColumns
            .map((pinnedKey) => {
                const colIndex = allColumns.findIndex((col) => (col.key || col.dataIndex) === pinnedKey)
                return { key: pinnedKey, position: colIndex }
            })
            .sort((a, b) => b.position - a.position) // Sort by position descending

        const lastPinnedColumn = pinnedColumnPositions[0] // Highest position
        isLastPinned = columnKey === lastPinnedColumn?.key
    }

    // Calculate left position (for css) based on actual column positions
    let leftPosition = 0
    if (isPinned && pinnedColumnWidths && allColumns) {
        // Find all pinned columns that come before this one in the table
        const pinnedColumnsBeforeThis = pinnedColumns.filter((pinnedKey) => {
            const pinnedKeyIndex = allColumns.findIndex((col) => (col.key || col.dataIndex) === pinnedKey)
            const thisColumnIndex = allColumns.findIndex((col) => (col.key || col.dataIndex) === columnKey)
            return pinnedKeyIndex < thisColumnIndex
        })

        // Sum up widths of pinned columns that come before this one
        for (const beforeKey of pinnedColumnsBeforeThis) {
            const beforePinnedIndex = pinnedColumns.indexOf(beforeKey)
            if (beforePinnedIndex >= 0) {
                leftPosition += pinnedColumnWidths[beforePinnedIndex] || DEFAULT_COLUMN_WIDTH
            }
        }
    }

    return { isPinned, isLastPinned, leftPosition }
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
