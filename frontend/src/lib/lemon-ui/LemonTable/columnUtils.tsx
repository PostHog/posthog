import { TZLabel } from 'lib/components/TZLabel'
import { Dayjs, dayjs } from 'lib/dayjs'

import { UserBasicType } from '~/types'

import { LemonTag } from '../LemonTag'
import { ProfilePicture } from '../ProfilePicture'
import { LemonTableColumn } from './types'

// Moved to a render-free leaf so LemonTable internals can use them without importing
// this file's column factories (and their TZLabel/eventUsageLogic graph); re-exported
// here for existing importers.
export { DEFAULT_COLUMN_WIDTH, determineColumnKey, getStickyColumnInfo } from './columnLayoutUtils'

export function atColumn<T extends Record<string, any>>(
    key: keyof T,
    title: string,
    getValue?: (record: T) => string | null | undefined
): LemonTableColumn<T, typeof key> {
    return {
        title: title,
        dataIndex: key,
        render: function RenderAt(value, record) {
            const actualValue = getValue ? getValue(record) : value
            return actualValue ? (
                <div className="whitespace-nowrap text-right">
                    <TZLabel time={actualValue} />
                </div>
            ) : (
                <span className="text-secondary">—</span>
            )
        },
        align: 'right',
        defaultSortOrder: -1,
        sorter: (a, b) => {
            const aValue = getValue ? getValue(a) : a[key]
            const bValue = getValue ? getValue(b) : b[key]
            return dayjs(aValue || 0).diff(bValue || 0)
        },
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
