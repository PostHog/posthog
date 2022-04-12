import React from 'react'
import { ArrowDownOutlined, ArrowUpOutlined, MenuOutlined } from '@ant-design/icons'

/** Sorting state. */
export interface Sorting {
    columnKey: string
    /** 1 means ascending, -1 means descending. */
    order: 1 | -1
}

export function getNextSorting(
    currentSorting: Sorting | null,
    selectedColumnKey: string,
    disableSortingCancellation: boolean
): Sorting | null {
    if (
        !currentSorting ||
        currentSorting.columnKey !== selectedColumnKey ||
        (currentSorting.order === -1 && disableSortingCancellation)
    ) {
        return { columnKey: selectedColumnKey, order: 1 }
    } else if (currentSorting.order === 1) {
        return { columnKey: selectedColumnKey, order: -1 }
    } else {
        return null
    }
}

export function SortingIndicator({ order }: { order: Sorting['order'] | null }): JSX.Element {
    return (
        <div
            style={{
                fontSize: 10,
                marginLeft: 8,
                whiteSpace: 'nowrap',
                width: 20,
                display: 'flex',
                justifyContent: 'center',
            }}
        >
            {order === -1 ? <ArrowDownOutlined /> : order === 1 ? <ArrowUpOutlined /> : null}
            <MenuOutlined />
        </div>
    )
}
