import { LemonButton, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { BuiltLogic, useActions, useValues } from 'kea'
import { Children, isValidElement, MouseEvent, useCallback, useMemo } from 'react'

import { DataSourceLogic } from './types'

export interface DataTableProps<T> {
    dataSource: BuiltLogic<DataSourceLogic<T>>
    className?: string
    children?: React.ReactNode
    embedded?: boolean
    onRowClick?: (item: T, evt: MouseEvent) => void
}

export function DataTable<T extends Record<string, any>>({
    dataSource,
    className,
    embedded = false,
    onRowClick,
    children,
}: DataTableProps<T>): JSX.Element {
    const { items, itemsLoading } = useValues(dataSource)

    const columns = useMemo(() => {
        return Children.toArray(children)
            .filter((child) => isValidElement(child))
            .map((child) => {
                const props = child.props as DataTableColumnProps<T>
                return {
                    title: props.title,
                    align: props.align,
                    width: props.width,
                    render: (_, record: T, recordIndex: number, rowCount: number) =>
                        props.cellRenderer(record, recordIndex, rowCount),
                } as LemonTableColumn<T, keyof T | undefined>
            })
    }, [children])

    const onRow = useCallback(
        (record: T) => {
            return {
                // onClick handler adds style to row we don't want
                onMouseDown: (event: MouseEvent) => {
                    onRowClick?.(record, event)
                },
                className: onRowClick ? 'cursor-pointer hover:bg-fill-highlight-50' : '',
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
            footer={<DataTableFooter dataSource={dataSource} />}
        />
    )
}

export function DataTableFooter<T extends Record<string, any>>({ dataSource }: DataTableProps<T>): JSX.Element {
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

export interface DataTableColumnProps<T> {
    title?: string
    align?: 'left' | 'right' | 'center'
    width?: string
    cellRenderer: (item: T, itemIdx: number, rowCount: number) => React.ReactNode
}

/* eslint-disable @typescript-eslint/no-unused-vars */
export function DataTableColumn<T>(_: DataTableColumnProps<T>): JSX.Element {
    /* eslint-enable @typescript-eslint/no-unused-vars */
    return <></>
}
