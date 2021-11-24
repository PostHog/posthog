import React, { HTMLProps, useState } from 'react'
import { IconUnfoldLess, IconUnfoldMore } from '../icons'
import { LemonButton } from '../LemonButton'
import { ExpandableConfig, LemonTableColumns } from './types'

export interface TableRowProps<T extends Record<string, any>> {
    record: T
    recordIndex: number
    rowKey: keyof T | undefined
    rowClassName: string | undefined
    columns: LemonTableColumns<T>
    onRow: ((record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>) | undefined
    expandable: ExpandableConfig<T> | undefined
}

export function TableRow<T extends Record<string, any>>({
    record,
    recordIndex,
    rowKey,
    rowClassName,
    columns,
    onRow,
    expandable,
}: TableRowProps<T>): JSX.Element {
    const [isRowExpanded, setIsRowExpanded] = useState(false)
    const rowExpandable: boolean = !!expandable?.rowExpandable?.(record)

    return (
        <>
            <tr data-row-key={rowKey ? record[rowKey] : recordIndex} {...onRow?.(record)} className={rowClassName}>
                {expandable && (
                    <td>
                        {rowExpandable && (
                            <LemonButton
                                type={isRowExpanded ? 'highlighted' : 'stealth'}
                                onClick={() => setIsRowExpanded((state) => !state)}
                                icon={isRowExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                tooltip={isRowExpanded ? 'Shrink' : 'Expand'}
                                compact
                            />
                        )}
                    </td>
                )}
                {columns.map((column, columnIndex) => {
                    const columnKeyRaw = column.key || column.dataIndex
                    const columnKeyOrIndex = columnKeyRaw ? String(columnKeyRaw) : columnIndex
                    const value = column.dataIndex ? record[column.dataIndex] : undefined
                    const contents = column.render ? column.render(value as T[keyof T], record, recordIndex) : value
                    return (
                        <td key={columnKeyOrIndex} className={column.className} style={{ textAlign: column.align }}>
                            {contents}
                        </td>
                    )
                })}
            </tr>

            {expandable && rowExpandable && isRowExpanded && (
                <tr>
                    <td colSpan={columns.length + 1}>{expandable.expandedRowRender(record, recordIndex)}</td>
                </tr>
            )}
        </>
    )
}
