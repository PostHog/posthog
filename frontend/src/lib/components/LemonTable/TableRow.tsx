import React, { HTMLProps, useState } from 'react'
import { IconUnfoldLess, IconUnfoldMore } from '../icons'
import { LemonButton } from '../LemonButton'
import { ExpandableConfig, LemonTableColumnGroup, TableCellRepresentation } from './types'
import clsx from 'clsx'

export interface TableRowProps<T extends Record<string, any>> {
    record: T
    recordIndex: number
    rowKeyDetermined: string | number
    rowClassNameDetermined: string | null | undefined
    rowRibbonColorDetermined: string | null | undefined
    rowStatusDetermined: 'highlighted' | null | undefined
    columnGroups: LemonTableColumnGroup<T>[]
    onRow: ((record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>) | undefined
    expandable: ExpandableConfig<T> | undefined
}

function TableRowRaw<T extends Record<string, any>>({
    record,
    recordIndex,
    rowKeyDetermined,
    rowClassNameDetermined,
    rowRibbonColorDetermined,
    rowStatusDetermined,
    columnGroups,
    onRow,
    expandable,
}: TableRowProps<T>): JSX.Element {
    const [isRowExpandedLocal, setIsRowExpanded] = useState(false)
    const rowExpandable: number = Number(
        !!expandable && (!expandable.rowExpandable || expandable.rowExpandable(record))
    )
    const isRowExpanded =
        !expandable?.isRowExpanded || expandable?.isRowExpanded?.(record) === -1
            ? isRowExpandedLocal
            : !!expandable?.isRowExpanded?.(record)

    return (
        <>
            <tr
                data-row-key={rowKeyDetermined}
                {...onRow?.(record)}
                className={clsx(
                    rowClassNameDetermined,
                    rowStatusDetermined && `LemonTable__tr--status-${rowStatusDetermined}`
                )}
            >
                {rowRibbonColorDetermined !== undefined && (
                    <td
                        className="LemonTable__ribbon"
                        style={{ backgroundColor: rowRibbonColorDetermined || 'transparent' }}
                    />
                )}
                {!!expandable && rowExpandable >= 0 && (
                    <td>
                        {!!rowExpandable && (
                            <LemonButton
                                status="stealth"
                                active={isRowExpanded}
                                onClick={() => {
                                    setIsRowExpanded(!isRowExpanded)
                                    if (isRowExpanded) {
                                        expandable?.onRowCollapse?.(record)
                                    } else {
                                        expandable?.onRowExpand?.(record)
                                    }
                                }}
                                icon={isRowExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                title={isRowExpanded ? 'Show less' : 'Show more'}
                            />
                        )}
                    </td>
                )}
                {columnGroups.flatMap((columnGroup, columnGroupIndex) =>
                    columnGroup.children.map((column, columnIndex) => {
                        const columnKeyRaw = column.key || column.dataIndex
                        const columnKeyOrIndex = columnKeyRaw ? String(columnKeyRaw) : columnIndex
                        const value = column.dataIndex ? record[column.dataIndex] : undefined
                        const contents = column.render ? column.render(value as T[keyof T], record, recordIndex) : value
                        const areContentsCellRepresentations: boolean =
                            !!contents && typeof contents === 'object' && !React.isValidElement(contents)
                        return (
                            <td
                                key={`LemonTable-td-${columnGroupIndex}-${columnKeyOrIndex}`}
                                className={clsx(
                                    columnIndex === columnGroup.children.length - 1 && 'LemonTable__boundary',
                                    column.className
                                )}
                                style={{ textAlign: column.align }}
                                {...(areContentsCellRepresentations ? (contents as TableCellRepresentation).props : {})}
                            >
                                {areContentsCellRepresentations
                                    ? (contents as TableCellRepresentation).children
                                    : contents}
                            </td>
                        )
                    })
                )}
            </tr>

            {expandable && !!rowExpandable && isRowExpanded && (
                <tr className="LemonTable__expansion">
                    {!expandable.noIndent && <td />}
                    <td
                        colSpan={
                            columnGroups.reduce((acc, columnGroup) => acc + columnGroup.children.length, 0) +
                            Number(!!expandable.noIndent)
                        }
                    >
                        {expandable.expandedRowRender(record, recordIndex)}
                    </td>
                </tr>
            )}
        </>
    )
}
// Without `memo` all rows get rendered when anything in the parent component (LemonTable) changes.
// This was most jarring when scrolling thet table from the very left or the very right – the simple addition
// of a class indicating that scrollability to `table` caused the component to lag due to unneded rerendering of rows.
export const TableRow = React.memo(TableRowRaw) as typeof TableRowRaw
