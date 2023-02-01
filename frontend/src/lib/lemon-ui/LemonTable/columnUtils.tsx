import { TZLabel } from 'lib/components/TZLabel' // TODO: Bring this into Lemon UI
import { Row } from 'antd'
import { ProfilePicture } from '../ProfilePicture'
import { LemonTableColumn } from './types'
import { UserBasicType } from '~/types'

export function createdAtColumn<T extends { created_at?: string | null }>(): LemonTableColumn<T, 'created_at'> {
    return {
        title: 'Created',
        dataIndex: 'created_at',
        render: function RenderCreatedAt(created_at) {
            return created_at ? (
                <div className="whitespace-nowrap text-right">
                    <TZLabel time={created_at} />
                </div>
            ) : (
                <span style={{ color: 'var(--muted)' }}>—</span>
            )
        },
        align: 'right',
        sorter: (a, b) => (new Date(a.created_at || 0) > new Date(b.created_at || 0) ? 1 : -1),
    }
}

export function createdByColumn<T extends { created_by?: UserBasicType | null }>(): LemonTableColumn<T, 'created_by'> {
    return {
        title: 'Created by',
        dataIndex: 'created_by',
        render: function Render(_: any, item) {
            const { created_by } = item
            return (
                <Row align="middle" wrap={false}>
                    {created_by && (
                        <ProfilePicture name={created_by.first_name} email={created_by.email} size="md" showName />
                    )}
                </Row>
            )
        },
        sorter: (a, b) =>
            (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                b.created_by?.first_name || b.created_by?.email || ''
            ),
    }
}
