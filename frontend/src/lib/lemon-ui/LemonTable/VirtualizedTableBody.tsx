import clsx from 'clsx'
import React, { CSSProperties, HTMLProps, useMemo, useRef } from 'react'
import { List, useListRef } from 'react-window'

import { AutoSizer } from 'lib/components/AutoSizer'
import { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { getStickyColumnInfo } from './columnUtils'
import { LemonTableColumn, LemonTableColumnGroup, TableCellRepresentation } from './types'

export interface VirtualizedRowData {
    dataSource: Record<string, any>[]
    columns: LemonTableColumn<Record<string, any>, any>[]
    columnGroups: LemonTableColumnGroup<Record<string, any>>[]
    gridTemplateColumns: string
    rowKey?: string | ((record: Record<string, any>, rowIndex: number) => string | number)
    rowClassName?: string | ((record: Record<string, any>, rowIndex: number) => string | null)
    rowRibbonColor?: string | ((record: Record<string, any>, rowIndex: number) => string | null | undefined)
    rowStatus?:
        | 'highlighted'
        | 'highlight-new'
        | ((record: Record<string, any>, rowIndex: number) => 'highlighted' | 'highlight-new' | null)
    onRow?: (record: Record<string, any>, index: number) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    firstColumnSticky?: boolean
    pinnedColumns?: string[]
    pinnedColumnWidths?: number[]
    rowActions?: (record: Record<string, any>, recordIndex: number) => React.ReactNode | null
    startIndex: number
    rowCount: number
}

function isTableCellRepresentation(
    contents: React.ReactNode | TableCellRepresentation
): contents is TableCellRepresentation {
    return !!contents && typeof contents === 'object' && !React.isValidElement(contents)
}

function VirtualizedRow({
    index,
    style,
    dataSource,
    columns,
    columnGroups,
    gridTemplateColumns,
    rowKey,
    rowClassName,
    rowRibbonColor,
    rowStatus,
    onRow,
    firstColumnSticky,
    pinnedColumns,
    pinnedColumnWidths,
    rowActions,
    startIndex,
    rowCount,
}: {
    index: number
    style: CSSProperties
    ariaAttributes: Record<string, unknown>
} & VirtualizedRowData): JSX.Element {
    const record = dataSource[index]
    const recordIndex = startIndex + index

    const rowKeyDetermined =
        rowKey != null
            ? typeof rowKey === 'function'
                ? rowKey(record, index)
                : (record[rowKey] ?? recordIndex)
            : recordIndex

    const rowClassNameDetermined = typeof rowClassName === 'function' ? rowClassName(record, index) : rowClassName
    const rowRibbonColorDetermined =
        typeof rowRibbonColor === 'function'
            ? rowRibbonColor(record, index) || 'var(--color-border-primary)'
            : rowRibbonColor
    const rowStatusDetermined = typeof rowStatus === 'function' ? rowStatus(record, index) : rowStatus

    const { className: onRowClassName, style: onRowStyle, ...extraProps } = onRow?.(record, recordIndex) || {}

    return (
        <div
            style={
                {
                    ...style,
                    '--row-ribbon-color': rowRibbonColorDetermined || undefined,
                    ...onRowStyle,
                } as CSSProperties
            }
            data-row-key={rowKeyDetermined}
            className={clsx(
                'LemonTable__virtualized-row',
                rowClassNameDetermined,
                rowStatusDetermined && `LemonTable__row--status-${rowStatusDetermined}`,
                extraProps?.onClick ? 'cursor-pointer hover:bg-accent-highlight-secondary' : undefined,
                onRowClassName
            )}
            {...extraProps}
        >
            <div className="LemonTable__virtualized-cells" style={{ gridTemplateColumns }}>
                {columnGroups.flatMap((columnGroup, columnGroupIndex) =>
                    columnGroup.children
                        .filter((column) => !column.isHidden)
                        .map((column, columnIndex) => {
                            const columnKeyRaw = column.key || column.dataIndex
                            const columnKeyOrIndex = columnKeyRaw ? String(columnKeyRaw) : columnIndex
                            const value = column.dataIndex != null ? record[column.dataIndex] : undefined
                            const rawContents = column.render
                                ? column.render(value, record, recordIndex, rowCount)
                                : value

                            const cellActionsOverlay = column.cellActions
                                ? column.cellActions(value, record, recordIndex)
                                : null
                            const contents =
                                cellActionsOverlay && !isTableCellRepresentation(rawContents) ? (
                                    <div className="flex items-center gap-1">
                                        <div className="flex-1 min-w-0">{rawContents}</div>
                                        <div className="flex-shrink-0">
                                            <More overlay={cellActionsOverlay} size="xsmall" />
                                        </div>
                                    </div>
                                ) : (
                                    rawContents
                                )

                            const isSticky = firstColumnSticky && columnGroupIndex === 0 && columnIndex === 0

                            const { isSticky: isColumnSticky, leftPosition } = getStickyColumnInfo(
                                columnKeyOrIndex.toString(),
                                pinnedColumns,
                                pinnedColumnWidths,
                                columns
                            )

                            const extraCellProps =
                                isTableCellRepresentation(contents) && contents.props ? contents.props : {}

                            return (
                                <div
                                    key={`col-${columnGroupIndex}-${columnKeyOrIndex}`}
                                    className={clsx(
                                        'LemonTable__virtualized-cell',
                                        columnIndex === 0 && 'LemonTable__boundary',
                                        isSticky && 'LemonTable__cell--sticky',
                                        isColumnSticky && 'LemonTable__cell--pinned',
                                        column.align && `text-${column.align}`,
                                        typeof column.className === 'function'
                                            ? column.className(value, record, recordIndex)
                                            : column.className
                                    )}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        ...(typeof column.style === 'function'
                                            ? column.style(value, record, recordIndex)
                                            : column.style),
                                        ...(isColumnSticky ? { left: `${leftPosition}px` } : {}),
                                    }}
                                    {...extraCellProps}
                                >
                                    {isTableCellRepresentation(contents) ? contents.children : contents}
                                </div>
                            )
                        })
                )}
                {rowActions && (
                    <div className="LemonTable__virtualized-cell w-0">
                        {(() => {
                            const actionsOverlay = rowActions(record, recordIndex)
                            return actionsOverlay ? <More overlay={actionsOverlay} /> : null
                        })()}
                    </div>
                )}
            </div>
        </div>
    )
}

export interface VirtualizedTableBodyProps {
    dataSource: Record<string, any>[]
    columns: LemonTableColumn<Record<string, any>, any>[]
    columnGroups: LemonTableColumnGroup<Record<string, any>>[]
    gridTemplateColumns: string
    rowHeight: number
    rowKey?: string | ((record: Record<string, any>, rowIndex: number) => string | number)
    rowClassName?: string | ((record: Record<string, any>, rowIndex: number) => string | null)
    rowRibbonColor?: string | ((record: Record<string, any>, rowIndex: number) => string | null | undefined)
    rowStatus?:
        | 'highlighted'
        | 'highlight-new'
        | ((record: Record<string, any>, rowIndex: number) => 'highlighted' | 'highlight-new' | null)
    onRow?: (record: Record<string, any>, index: number) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    firstColumnSticky?: boolean
    pinnedColumns?: string[]
    pinnedColumnWidths?: number[]
    rowActions?: (record: Record<string, any>, recordIndex: number) => React.ReactNode | null
    startIndex: number
    loading?: boolean
    loadingSkeletonRows?: number
    emptyState?: React.ReactNode
    nouns?: [string, string]
}

export function VirtualizedTableBody({
    dataSource,
    columns,
    columnGroups,
    gridTemplateColumns,
    rowHeight,
    rowKey,
    rowClassName,
    rowRibbonColor,
    rowStatus,
    onRow,
    firstColumnSticky,
    pinnedColumns,
    pinnedColumnWidths,
    rowActions,
    startIndex,
    loading,
    loadingSkeletonRows = 1,
    emptyState,
    nouns = ['entry', 'entries'],
}: VirtualizedTableBodyProps): JSX.Element {
    const listRef = useListRef(null)
    const containerRef = useRef<HTMLDivElement>(null)

    const rowProps = useMemo(
        (): VirtualizedRowData => ({
            dataSource,
            columns,
            columnGroups,
            gridTemplateColumns,
            rowKey: rowKey as VirtualizedRowData['rowKey'],
            rowClassName: rowClassName as VirtualizedRowData['rowClassName'],
            rowRibbonColor: rowRibbonColor as VirtualizedRowData['rowRibbonColor'],
            rowStatus: rowStatus as VirtualizedRowData['rowStatus'],
            onRow: onRow as VirtualizedRowData['onRow'],
            firstColumnSticky,
            pinnedColumns,
            pinnedColumnWidths,
            rowActions: rowActions as VirtualizedRowData['rowActions'],
            startIndex,
            rowCount: dataSource.length,
        }),
        [
            dataSource,
            columns,
            columnGroups,
            gridTemplateColumns,
            rowKey,
            rowClassName,
            rowRibbonColor,
            rowStatus,
            onRow,
            firstColumnSticky,
            pinnedColumns,
            pinnedColumnWidths,
            rowActions,
            startIndex,
        ]
    )

    if (dataSource.length === 0) {
        if (loading) {
            return (
                <div className="LemonTable__virtualized-empty">
                    {Array(loadingSkeletonRows)
                        .fill(null)
                        .map((_, rowIndex) => (
                            <div
                                key={rowIndex}
                                className="LemonTable__virtualized-cells"
                                style={{ gridTemplateColumns, height: rowHeight }}
                            >
                                {columns
                                    .filter((col) => !col.isHidden)
                                    .map((_, colIndex) => (
                                        <div key={colIndex} className="LemonTable__virtualized-cell">
                                            <LemonSkeleton />
                                        </div>
                                    ))}
                            </div>
                        ))}
                </div>
            )
        }
        return (
            <div className="LemonTable__virtualized-empty LemonTable__empty-state">
                {emptyState || `No ${nouns[1]}`}
            </div>
        )
    }

    return (
        <div ref={containerRef} className="LemonTable__virtualized-body">
            <AutoSizer
                renderProp={({ height, width }: SizeProps) =>
                    height && width ? (
                        <List<VirtualizedRowData>
                            style={{ height, width }}
                            overscanCount={20}
                            rowCount={dataSource.length}
                            rowHeight={rowHeight}
                            rowComponent={VirtualizedRow}
                            rowProps={rowProps}
                            listRef={listRef}
                        />
                    ) : null
                }
            />
        </div>
    )
}
