import React, { HTMLProps, useState } from 'react'
import { IconUnfoldLess, IconUnfoldMore } from '../icons'
import { LemonButton } from '../LemonButton'
import { ExpandableConfig, LemonTableColumns, TableCellRepresentation } from './types'

export interface TableRowProps<T extends Record<string, any>> {
    record: T
    recordIndex: number
    rowKeyDetermined: string | number
    rowClassNameDetermined: string | undefined
    columns: LemonTableColumns<T>
    onRow: ((record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>) | undefined
    expandable: ExpandableConfig<T> | undefined
}

function TableRowRaw<T extends Record<string, any>>({
    record,
    recordIndex,
    rowKeyDetermined,
    rowClassNameDetermined,
    columns,
    onRow,
    expandable,
}: TableRowProps<T>): JSX.Element {
    const [isRowExpanded, setIsRowExpanded] = useState(false)
    const rowExpandable: number = Number(
        !!expandable && (!expandable.rowExpandable || expandable.rowExpandable(record))
    )

    return (
        <>
            <tr data-row-key={rowKeyDetermined} {...onRow?.(record)} className={rowClassNameDetermined}>
                {!!expandable && rowExpandable >= 0 && (
                    <td>
                        {rowExpandable && (
                            <LemonButton
                                type={isRowExpanded ? 'highlighted' : 'stealth'}
                                onClick={() => setIsRowExpanded((state) => !state)}
                                icon={isRowExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                title={isRowExpanded ? 'Show less' : 'Show more'}
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
                    const areContentsCellRepresentations: boolean =
                        !!contents && typeof contents === 'object' && !React.isValidElement(contents)
                    return (
                        <td
                            key={`LemonTable-td-${columnKeyOrIndex}`}
                            className={column.className}
                            style={{ textAlign: column.align }}
                            {...(areContentsCellRepresentations ? (contents as TableCellRepresentation).props : {})}
                        >
                            {areContentsCellRepresentations ? (contents as TableCellRepresentation).children : contents}
                        </td>
                    )
                })}
            </tr>

            {expandable && rowExpandable && isRowExpanded && (
                <tr className="LemonTable__expansion">
                    <td />
                    <td colSpan={columns.length}>{expandable.expandedRowRender(record, recordIndex)}</td>
                </tr>
            )}
        </>
    )
}
// Without `memo` all rows get rendered when anything in the parent component (LemonTable) changes.
// This was most jarring when scrolling thet table from the very left or the very right – the simple addition
// of a class indicating that scrollability to `table` caused the component to lag due to unneded rerendering of rows.
export const TableRow = React.memo(TableRowRaw) as typeof TableRowRaw
