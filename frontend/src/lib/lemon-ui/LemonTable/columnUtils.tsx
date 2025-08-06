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
