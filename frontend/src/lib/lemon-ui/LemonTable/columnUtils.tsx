import { TZLabel } from 'lib/components/TZLabel'
import { Dayjs, dayjs } from 'lib/dayjs'

import { UserBasicType } from '~/types'

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
                <span className="text-muted">—</span>
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
                <div className={'flex flex-row items-center flex-nowrap'}>
                    {created_by && (
                        <ProfilePicture name={created_by.first_name} email={created_by.email} size="md" showName />
                    )}
                </div>
            )
        },
        sorter: (a, b) =>
            (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                b.created_by?.first_name || b.created_by?.email || ''
            ),
    }
}
