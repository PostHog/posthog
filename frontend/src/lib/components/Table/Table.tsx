import React from 'react'
import { uniqueBy } from 'lib/utils'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { TZLabel } from '../TimezoneAware'
import { normalizeColumnTitle } from 'lib/components/Table/utils'

export function createdAtColumn(): Record<string, any> {
    return {
        title: normalizeColumnTitle('Created'),
        render: function RenderCreatedAt(_: any, item: Record<string, any>): JSX.Element | undefined | '' {
            return (
                item.created_at && (
                    <div style={{ whiteSpace: 'nowrap' }}>
                        <TZLabel time={item.created_at} />
                    </div>
                )
            )
        },
        sorter: (a: Record<string, any>, b: Record<string, any>) =>
            new Date(a.created_at) > new Date(b.created_at) ? 1 : -1,
    }
}

export function createdByColumn(items: Record<string, any>[]): Record<string, any> {
    const { user } = useValues(userLogic)
    return {
        title: normalizeColumnTitle('Created by'),
        render: function Render(_: any, item: any) {
            return (
                <div style={{ maxWidth: 250, width: 'auto' }}>
                    {item.created_by ? item.created_by.first_name || item.created_by.email : '-'}
                </div>
            )
        },
        filters: uniqueBy(
            items.map((item: Record<string, any>) => {
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
        onFilter: (value: string, item: Record<string, any>) =>
            (value === null && item.created_by === null) || item.created_by?.uuid === value,
        sorter: (a: Record<string, any>, b: Record<string, any>) =>
            (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                b.created_by?.first_name || b.created_by?.email || ''
            ),
    }
}
