import clsx from 'clsx'
import React, { HTMLProps, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { getStickyColumnInfo } from './columnUtils'
import { ExpandableConfig, LemonTableColumn, LemonTableColumnGroup, TableCellRepresentation } from './types'

export interface TableRowProps<T extends Record<string, any>> {
    record: T
    recordIndex: number
    rowKeyDetermined: string | number
    rowClassNameDetermined: string | null | undefined
    rowRibbonColorDetermined: string | null | undefined
    rowStatusDetermined: 'highlighted' | null | undefined
    columnGroups: LemonTableColumnGroup<T>[]
    onRow: ((record: T, index: number) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>) | undefined
    expandable: ExpandableConfig<T> | undefined
    firstColumnSticky: boolean | undefined
    rowCount: number
    pinnedColumns?: string[]
    pinnedColumnWidths?: number[]
    columns?: LemonTableColumn<T, any>[]
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
    firstColumnSticky,
    rowCount,
    pinnedColumns,
    pinnedColumnWidths,
    columns,
}: TableRowProps<T>): JSX.Element {
    const [isRowExpandedLocal, setIsRowExpanded] = useState(false)
    const rowExpandable: number = Number(
        !!expandable && (!expandable.rowExpandable || expandable.rowExpandable(record, recordIndex))
    )
    const isRowExpanded =
        !expandable?.isRowExpanded || expandable?.isRowExpanded?.(record, recordIndex) === -1
            ? isRowExpandedLocal
            : !!expandable?.isRowExpanded?.(record, recordIndex)

    const isRowExpansionToggleShownLocal = !!expandable && rowExpandable >= 0
    const isRowExpansionToggleShown = expandable?.showRowExpansionToggle ?? isRowExpansionToggleShownLocal

    const expandedRowClassNameDetermined =
        expandable &&
        isRowExpanded &&
        expandable.expandedRowClassName &&
        (typeof expandable.expandedRowClassName === 'function'
            ? expandable.expandedRowClassName(record, recordIndex)
            : expandable.expandedRowClassName)

    const { className, style, ...extraProps } = onRow?.(record, recordIndex) || {}

    return (
        <>
            <tr
                data-row-key={rowKeyDetermined}
                className={clsx(
                    rowClassNameDetermined,
                    rowStatusDetermined && `LemonTable__row--status-${rowStatusDetermined}`,
                    extraProps?.onClick ? 'cursor-pointer hover:bg-accent-highlight-secondary' : undefined,
                    className
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--row-ribbon-color': rowRibbonColorDetermined || undefined, ...style } as React.CSSProperties}
                {...extraProps}
            >
                {isRowExpansionToggleShown && (
                    <td className="LemonTable__toggle">
                        {!!rowExpandable && (
                            <LemonButton
                                noPadding
                                active={isRowExpanded}
                                onClick={() => {
                                    setIsRowExpanded(!isRowExpanded)
                                    if (isRowExpanded) {
                                        expandable?.onRowCollapse?.(record, recordIndex)
                                    } else {
                                        expandable?.onRowExpand?.(record, recordIndex)
                                    }
                                }}
                                icon={isRowExpanded ? <IconCollapse /> : <IconExpand />}
                                title={isRowExpanded ? 'Show less' : 'Show more'}
                            />
                        )}
                    </td>
                )}
                {columnGroups.flatMap((columnGroup, columnGroupIndex) =>
                    columnGroup.children
                        .filter((column) => !column.isHidden)
                        .map((column, columnIndex) => {
                            const columnKeyRaw = column.key || column.dataIndex
                            const columnKeyOrIndex = columnKeyRaw ? String(columnKeyRaw) : columnIndex
                            // != is intentional to catch undefined too
                            const value = column.dataIndex != null ? record[column.dataIndex] : undefined
                            const contents = column.render
                                ? column.render(value as T[keyof T], record, recordIndex, rowCount)
                                : value
                            const isSticky = firstColumnSticky && columnGroupIndex === 0 && columnIndex === 0

                            // Check if this column is pinned
                            const { isSticky: isColumnSticky, leftPosition } = getStickyColumnInfo(
                                columnKeyOrIndex.toString(),
                                pinnedColumns,
                                pinnedColumnWidths,
                                columns
                            )

                            const extraCellProps =
                                isTableCellRepresentation(contents) && contents.props ? contents.props : {}
                            return (
                                <td
                                    key={`col-${columnGroupIndex}-${columnKeyOrIndex}`}
                                    className={clsx(
                                        columnIndex === 0 && 'LemonTable__boundary',
                                        isSticky && 'LemonTable__cell--sticky',
                                        isColumnSticky && 'LemonTable__cell--pinned',
                                        column.align && `text-${column.align}`,
                                        typeof column.className === 'function'
                                            ? column.className(value as T[keyof T], record, recordIndex)
                                            : column.className
                                    )}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        ...(typeof column.style === 'function'
                                            ? column.style(value as T[keyof T], record, recordIndex)
                                            : column.style),
                                        ...(isColumnSticky ? { left: `${leftPosition}px` } : {}),
                                    }}
                                    {...extraCellProps}
                                >
                                    {isTableCellRepresentation(contents) ? contents.children : contents}
                                </td>
                            )
                        })
                )}
            </tr>

            {expandable && !!rowExpandable && isRowExpanded && (
                <tr className={clsx('LemonTable__expansion', expandedRowClassNameDetermined)}>
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

function isTableCellRepresentation(
    contents: React.ReactNode | TableCellRepresentation
): contents is TableCellRepresentation {
    return !!contents && typeof contents === 'object' && !React.isValidElement(contents)
}
