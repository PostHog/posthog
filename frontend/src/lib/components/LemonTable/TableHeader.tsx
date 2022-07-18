import React from 'react'
import { ExpandableConfig, LemonTableColumn, LemonTableColumnGroup } from './types'
import { determineColumnKey } from 'lib/utils'
import { Tooltip } from '../Tooltip'
import { SortingIndicator } from './sorting'
import clsx from 'clsx'

export interface TableHeaderProps<T extends Record<string, any>> {
    columnGroups: LemonTableColumnGroup<T>[]
    onSort: (column: LemonTableColumn<T, keyof T | undefined>) => (() => void) | undefined
    getTooltipTitle: (column: LemonTableColumn<T, keyof T | undefined>) => string | undefined
    getSortingOrder: (column: LemonTableColumn<T, keyof T | undefined>) => 1 | -1 | null
    uppercaseHeader?: boolean
    expandable?: ExpandableConfig<T> | undefined
    rowRibbonColor?: string | ((record: T) => string | null)
    fixedWidths?: Record<number, number>
    lastFixedIndex?: [number, number]
    isScrollable?: boolean
}

export function TableHeader<T extends Record<string, any>>({
    columnGroups,
    onSort,
    getTooltipTitle,
    getSortingOrder,
    uppercaseHeader,
    expandable,
    rowRibbonColor,
    fixedWidths,
    lastFixedIndex,
    isScrollable,
}: TableHeaderProps<T>): JSX.Element {
    return (
        <thead style={!uppercaseHeader ? { textTransform: 'none', letterSpacing: 'normal' } : undefined}>
            {columnGroups.some((group) => group.title) && (
                <tr className="LemonTable__row--grouping">
                    {!!rowRibbonColor && <th className="LemonTable__ribbon" /> /* Ribbon column */}
                    {!!expandable && <th /> /* Expand/collapse column */}
                    {columnGroups.map((columnGroup, columnGroupIndex) => (
                        <th
                            key={`LemonTable-th-group-${columnGroupIndex}`}
                            colSpan={columnGroup.children.length}
                            className="LemonTable__boundary"
                        >
                            {columnGroup.title}
                        </th>
                    ))}
                </tr>
            )}
            <tr>
                {!!rowRibbonColor && <th className="LemonTable__ribbon" /> /* Ribbon column */}
                {!!expandable && <th /> /* Expand/collapse column */}
                {columnGroups.flatMap((columnGroup, columnGroupIndex) =>
                    columnGroup.children.map((column, columnIndex) => {
                        let style: React.CSSProperties = { textAlign: column.align }
                        if (fixedWidths && column.isFixed) {
                            let result = 0
                            for (const [index, width] of Object.entries(fixedWidths)) {
                                if (parseInt(index) < columnIndex) {
                                    result += width
                                }
                            }
                            style = { ...style, left: result }
                        }
                        return (
                            <th
                                key={`LemonTable-th-${columnGroupIndex}-${determineColumnKey(column) || columnIndex}`}
                                className={clsx(
                                    column.sorter && 'LemonTable__header--actionable',
                                    columnIndex === columnGroup.children.length - 1 && 'LemonTable__boundary',
                                    fixedWidths && column.isFixed && 'LemonTable__sticky',
                                    lastFixedIndex &&
                                        lastFixedIndex[0] === columnGroupIndex &&
                                        lastFixedIndex[1] === columnIndex &&
                                        'LemonTable__sticky--boundary',
                                    isScrollable && 'LemonTable__sticky--vertical-boundary',
                                    column.className
                                )}
                                style={style}
                                onClick={onSort(column)}
                            >
                                <Tooltip title={getTooltipTitle(column)}>
                                    <div
                                        className="LemonTable__header-content"
                                        style={{ justifyContent: column.align }}
                                    >
                                        {column.title}
                                        {column.sorter && <SortingIndicator order={getSortingOrder(column)} />}
                                    </div>
                                </Tooltip>
                            </th>
                        )
                    })
                )}
            </tr>
            <tr className="LemonTable__loader" />
        </thead>
    )
}
