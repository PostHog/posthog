import React from 'react'
import { uniqueBy } from 'lib/utils'
import { Created } from './Created'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export function createdAtColumn(): Record<string, any> {
    return {
        title: 'Created',
        render: function RenderCreatedAt(_, item: Record<string, any>): JSX.Element | undefined | '' {
            return item.created_at && <Created timestamp={item.created_at} />
        },
        sorter: (a: Record<string, any>, b: Record<string, any>) =>
            new Date(a.created_at) > new Date(b.created_at) ? 1 : -1,
    }
}

export function createdByColumn(items: Record<string, any>[]): Record<string, any> {
    const { user } = useValues(userLogic)
    return {
        title: 'Created by',
        render: function RenderCreatedBy(_, item: any) {
            return item.created_by ? item.created_by.first_name || item.created_by.email : '-'
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
                    value: item.created_by?.id,
                }
            }),
            (item) => item?.value
        ).sort((a, b) => {
            // Current user first
            if (a.value === user?.id) {
                return -10
            }
            if (b.value === user?.id) {
                return 10
            }
            return (a.text + '').localeCompare(b.text + '')
        }),
        onFilter: (value: string, item: Record<string, any>) =>
            (value === null && item.created_by === null) || item.created_by?.id === value,
        sorter: (a: Record<string, any>, b: Record<string, any>) =>
            (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                b.created_by?.first_name || b.created_by?.email || ''
            ),
    }
}
