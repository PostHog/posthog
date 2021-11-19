import React from 'react'
import { uniqueBy } from 'lib/utils'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { TZLabel } from '../TimezoneAware'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { ColumnType } from 'antd/lib/table'
import { Row } from 'antd'
import { ProfilePicture } from '../ProfilePicture'

export function createdAtColumn<T extends Record<string, any> = Record<string, any>>(): ColumnType<T> {
    return {
        title: normalizeColumnTitle('Created'),
        align: 'right',
        render: function RenderCreatedAt(_, item): JSX.Element | undefined | '' {
            return (
                item.created_at && (
                    <div style={{ whiteSpace: 'nowrap' }}>
                        <TZLabel time={item.created_at} />
                    </div>
                )
            )
        },
        sorter: (a, b) => (new Date(a.created_at) > new Date(b.created_at) ? 1 : -1),
    }
}

export function createdByColumn<T extends Record<string, any> = Record<string, any>>(items: T[]): ColumnType<T> {
    const { user } = useValues(userLogic)
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
        filters: uniqueBy(
            items.map((item: T) => {
                if (!item.created_by) {
                    return {
                        text: '(none)',
                        value: null,
                    }
                }
                return {
                    text: item.created_by?.first_name || item.created_by?.email,
                    value: item.created_by?.uuid,
                }
            }),
            (item) => item?.value
        ).sort((a, b) => {
            // Current user first
            if (a.value === user?.uuid) {
                return -10
            }
            if (b.value === user?.uuid) {
                return 10
            }
            return (a.text + '').localeCompare(b.text + '')
        }),
        onFilter: (value, item) => (value === null && item.created_by === null) || item.created_by?.uuid === value,
        sorter: (a, b) =>
            (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                b.created_by?.first_name || b.created_by?.email || ''
            ),
    }
}
