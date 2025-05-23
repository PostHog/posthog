import { LemonButton, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { BuiltLogic, useActions, useValues } from 'kea'
import { Children, isValidElement, MouseEvent, ReactElement, useCallback } from 'react'

import type { DataSourceLogic } from './types'

export interface DataSourceTableProps<T> {
    dataSource: BuiltLogic<DataSourceLogic<T>>
    className?: string
    children?: React.ReactNode
    embedded?: boolean
    onRowClick?: (item: T, evt: MouseEvent) => void
}

export function DataSourceTable<T extends Record<string, any>>({
    dataSource,
    className,
    embedded = false,
    onRowClick,
    children,
}: DataSourceTableProps<T>): JSX.Element {
    const { items, itemsLoading } = useValues(dataSource)

    const columns = Children.toArray(children)
        .filter((child) => isValidElement(child))
        .map((child) => {
            const props = (child as ReactElement).props as DataSourceTableColumnProps<T>
            return {
                title: props.title,
                align: props.align,
                width: props.width,
                render: (_, record: T, recordIndex: number, rowCount: number) =>
                    props.cellRenderer(record, recordIndex, rowCount),
            } as LemonTableColumn<T, keyof T | undefined>
        })

    const onRow = useCallback(
        (record: T) => {
            if (!onRowClick) {
                return {}
            }
            return {
                // onClick handler adds style to row we don't want
                onClick: (event: MouseEvent) => {
                    onRowClick(record, event)
                },
                className: 'hover:bg-fill-highlight-50',
            }
        },
        [onRowClick]
    )

    return (
        <LemonTable
            dataSource={items}
            columns={columns}
            loading={itemsLoading}
            embedded={embedded}
            onRow={onRow}
            className={className}
            footer={<DataSourceTableFooter dataSource={dataSource} />}
        />
    )
}

export function DataSourceTableFooter<T extends Record<string, any>>({
    dataSource,
}: Pick<DataSourceTableProps<T>, 'dataSource'>): JSX.Element {
    const { items, itemsLoading, canLoadNextData } = useValues(dataSource)
    const { loadNextData } = useActions(dataSource)

    return (
        <div className="p-1">
            <LemonButton
                className="rounded-tl-none rounded-tr-none"
                loading={itemsLoading}
                center
                fullWidth
                disabledReason={itemsLoading || !canLoadNextData ? 'Disabled' : ''}
                onClick={() => loadNextData()}
            >
                {itemsLoading && <span>Loading...</span>}
                {!itemsLoading && items.length === 0 && <span>No items found</span>}
                {!itemsLoading && !canLoadNextData && <span>No more entries</span>}
                {!itemsLoading && canLoadNextData && <span>Load More</span>}
            </LemonButton>
        </div>
    )
}

export interface DataSourceTableColumnProps<T> {
    title?: string
    align?: 'left' | 'right' | 'center'
    width?: string
    cellRenderer: (item: T, itemIdx: number, rowCount: number) => React.ReactNode
}

/* eslint-disable @typescript-eslint/no-unused-vars */
export function DataSourceTableColumn<T>(_: DataSourceTableColumnProps<T>): JSX.Element {
    /* eslint-enable @typescript-eslint/no-unused-vars */
    return <></>
}
