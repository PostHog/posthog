import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from '../ProfilePicture'
import { LemonTableColumn } from './types'
import { UserBasicType } from '~/types'
import { Dayjs, dayjs } from 'lib/dayjs'

export function createdAtColumn<T extends { created_at?: string | Dayjs | null }>(): LemonTableColumn<T, 'created_at'> {
    return {
        title: 'Created',
        dataIndex: 'created_at',
        render: function RenderCreatedAt(created_at) {
            return created_at ? (
                <div className="whitespace-nowrap text-right">
                    <TZLabel time={created_at} />
                </div>
            ) : (
                <span className="text-muted">—</span>
            )
        },
        align: 'right',
        sorter: (a, b) => dayjs(a.created_at || 0).diff(b.created_at || 0),
    }
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

export function updatedAtColumn<T extends { updated_at?: string | Dayjs | null }>(): LemonTableColumn<T, 'updated_at'> {
    return {
        title: 'Updated',
        dataIndex: 'updated_at',
        render: function RenderCreatedAt(updated_at) {
            return updated_at ? (
                <div className="whitespace-nowrap text-right">
                    <TZLabel time={updated_at} />
                </div>
            ) : (
                <span className="text-muted">—</span>
            )
        },
        align: 'right',
        sorter: (a, b) => dayjs(a.updated_at || 0).diff(b.updated_at || 0),
    }
}
