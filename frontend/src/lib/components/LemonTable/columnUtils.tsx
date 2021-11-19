import React from 'react'
import { TZLabel } from '../TimezoneAware'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { Row } from 'antd'
import { ProfilePicture } from '../ProfilePicture'
import { LemonTableColumn } from './LemonTable'
import { UserBasicType } from '~/types'

export function createdAtColumn<T extends { created_at: string | null }>(): LemonTableColumn<T, 'created_at'> {
    return {
        title: normalizeColumnTitle('Created'),
        align: 'right',
        render: function RenderCreatedAt(_, item) {
            return item.created_at ? (
                <div style={{ whiteSpace: 'nowrap' }}>
                    <TZLabel time={item.created_at} />
                </div>
            ) : (
                '-'
            )
        },
        sorter: (a, b) => (new Date(a.created_at || 0) > new Date(b.created_at || 0) ? 1 : -1),
    }
}

export function createdByColumn<T extends { created_by?: UserBasicType | null }>(): LemonTableColumn<T, 'created_by'> {
    return {
        title: normalizeColumnTitle('Created by'),
        render: function Render(_: any, item: any) {
            return (
                <Row align="middle" wrap={false}>
                    {item.created_by && (
                        <ProfilePicture name={item.created_by.first_name} email={item.created_by.email} size="md" />
                    )}
                    <div style={{ maxWidth: 250, width: 'auto', verticalAlign: 'middle', marginLeft: 8 }}>
                        {item.created_by ? item.created_by.first_name || item.created_by.email : '-'}
                    </div>
                </Row>
            )
        },
        sorter: (a, b) =>
            (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                b.created_by?.first_name || b.created_by?.email || ''
            ),
    }
}
