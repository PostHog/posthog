import '../../DataTable/DataTable.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { IconInfo, IconPin, IconPinFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumn, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { VisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { LoadNext } from '../../DataNode/LoadNext'
import { renderColumn } from '../../DataTable/renderColumn'
import { renderColumnMeta } from '../../DataTable/renderColumnMeta'
import { getContrastingTextClass } from '../colorUtils'
import { conditionalFormattingColor } from '../conditionalFormatting'
import { TableDataCell, TableRow, dataVisualizationLogic } from '../dataVisualizationLogic'
import { ColumnScalar } from '../types'

interface TableProps {
    query: VisualizationNode
    uniqueKey: string | number | undefined
    context: QueryContext<VisualizationNode> | undefined
    cachedResults: HogQLQueryResponse | undefined
    embedded?: boolean
    onInspect?: (record: Record<string, unknown>) => void
}

export const DEFAULT_PAGE_SIZE = 500

function formatColumnTitle(title: string): React.ReactNode {
    const parts = title.split(/([_-])/)
    if (parts.length === 1) {
        return title
    }
    // inserts <wbr> (word break opportunity tag) at dashes and unders for natural break points
    return parts.map((part, i) =>
        part === '_' || part === '-' ? (
            <React.Fragment key={i}>
                {part}
                <wbr />
            </React.Fragment>
        ) : (
            part
        )
    )
}

function getDisplayedColumnTitle(
    columnName: string,
    label: string | JSX.Element | undefined,
    query: VisualizationNode,
    context: QueryContext<VisualizationNode> | undefined
): React.ReactNode {
    const { title } = renderColumnMeta(columnName, query, context)
    return label || title || columnName
}

function isDateColumn(type: ColumnScalar | undefined): boolean {
    return type === 'DATE' || type === 'DATETIME'
}

// Numbers sort numerically, dates chronologically by epoch, everything else by a
// numeric-aware string compare, and empty cells sort to the bottom of an ascending sort.
export function compareTableCells(a: TableDataCell<any> | undefined, b: TableDataCell<any> | undefined): number {
    const aValue = a?.value
    const bValue = b?.value
    if (aValue == null && bValue == null) {
        return 0
    }
    if (aValue == null) {
        return 1
    }
    if (bValue == null) {
        return -1
    }
    if (typeof aValue === 'number' && typeof bValue === 'number') {
        return aValue - bValue
    }
    // Parse dates to epoch ms so values with different formats or timezones sort
    // chronologically rather than lexicographically.
    if (isDateColumn(a?.type) && isDateColumn(b?.type)) {
        const aTime = dayjs(aValue as string | number | Date).valueOf()
        const bTime = dayjs(bValue as string | number | Date).valueOf()
        if (!Number.isNaN(aTime) && !Number.isNaN(bTime)) {
            return aTime - bTime
        }
    }
    return String(aValue).localeCompare(String(bValue), undefined, { numeric: true })
}

// Plain-text representation of a cell, used as the hover title so clipped content is
// still visible on hover. The full value stays in the DOM (CSS ellipsis only), so
// selecting and copying a cell copies the whole value, not just the clipped portion.
// Fixed-layout tables can't size columns from their content, so estimate the widths from character counts.
// The estimates use the table font sizes and avoid DOM measurement, which would read every offscreen cell.
const CELL_CHARACTER_WIDTH = 7.5
const HEADER_CHARACTER_WIDTH = 8.5
const HEADER_ICONS_WIDTH = 44
const HEADER_LINE_MAX_WIDTH = 160
const CELL_HORIZONTAL_PADDING = 16
const EDGE_CELL_EXTRA_PADDING = 16
export const MIN_COLUMN_WIDTH = 64
export const MAX_COLUMN_WIDTH = 320
const COLUMN_WIDTH_SAMPLE_CELLS = 5000
const MIN_COLUMN_WIDTH_SAMPLE_ROWS = 10

function getCellTextLength(cell: TableDataCell<any>): number {
    if (cell.isTransposedHeader && cell.sourceColumnName) {
        return cell.sourceColumnName.length
    }
    if (cell.formattedValue !== null && typeof cell.formattedValue === 'object') {
        return Infinity
    }
    return String(cell.formattedValue ?? cell.value ?? '').length
}

/** Estimates pixel widths that fit each column's header and a sample of its cells. */
export function estimateColumnWidths(
    columnTitles: string[],
    rowCount: number,
    getCell: (sampleRowIndex: number, columnIndex: number) => TableDataCell<any>
): number[] {
    const columnCount = columnTitles.length
    // Keep the total number of formatted cells within the budget. Very wide tables (e.g. a transposed
    // result) sample a spread of columns, and the other columns reuse the typical sampled width.
    const minSampleRows = Math.max(1, Math.min(MIN_COLUMN_WIDTH_SAMPLE_ROWS, rowCount))
    const sampledColumnCount = Math.min(columnCount, Math.floor(COLUMN_WIDTH_SAMPLE_CELLS / minSampleRows))
    const sampleRowCount = Math.min(rowCount, Math.floor(COLUMN_WIDTH_SAMPLE_CELLS / Math.max(1, sampledColumnCount)))
    // Spread the sample over the whole result, so a long tail of wider values still counts
    const sampleRowIndexes = Array.from({ length: sampleRowCount }, (_, index) =>
        Math.floor((index * rowCount) / sampleRowCount)
    )

    const longestCellLengths = new Map<number, number>()
    for (let index = 0; index < sampledColumnCount; index++) {
        const columnIndex = Math.floor((index * columnCount) / sampledColumnCount)
        let longestCellLength = 0
        for (const rowIndex of sampleRowIndexes) {
            longestCellLength = Math.max(longestCellLength, getCellTextLength(getCell(rowIndex, columnIndex)))
            if (longestCellLength * CELL_CHARACTER_WIDTH >= MAX_COLUMN_WIDTH) {
                break
            }
        }
        longestCellLengths.set(columnIndex, longestCellLength)
    }
    const sampledLengths = [...longestCellLengths.values()].sort((a, b) => a - b)
    const typicalCellLength = sampledLengths[Math.floor(sampledLengths.length / 2)] ?? 0

    return columnTitles.map((title, columnIndex) => {
        // Headers wrap at spaces, dashes, and underscores, so only the longest segment must fit on one line
        const longestTitleSegment = Math.max(0, ...title.split(/[\s_-]+/).map((segment) => segment.length + 1))
        const headerWidth =
            Math.max(
                longestTitleSegment * HEADER_CHARACTER_WIDTH,
                Math.min(title.length * HEADER_CHARACTER_WIDTH, HEADER_LINE_MAX_WIDTH)
            ) + HEADER_ICONS_WIDTH

        const longestCellLength = longestCellLengths.get(columnIndex) ?? typicalCellLength
        const isEdgeColumn = columnIndex === 0 || columnIndex === columnCount - 1
        const padding = CELL_HORIZONTAL_PADDING + (isEdgeColumn ? EDGE_CELL_EXTRA_PADDING : 0)
        const contentWidth = Math.max(headerWidth, longestCellLength * CELL_CHARACTER_WIDTH)
        return Math.round(Math.min(MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, contentWidth + padding)))
    })
}

function getCellTitle(cell: TableDataCell<any>): string | undefined {
    if (typeof cell.formattedValue === 'string') {
        return cell.formattedValue
    }
    if (typeof cell.value === 'string' || typeof cell.value === 'number') {
        return String(cell.value)
    }
    return undefined
}

// Defined at module level so the tooltip's `onOpen` effect doesn't re-run, and re-capture, on every render
const captureColumnDescriptionViewed = (): void => {
    posthog.capture('sql column description viewed')
}

// Header labels are clamped to a few lines with a CSS ellipsis when they don't fit. The full text stays
// in the DOM, so we compare the rendered box against the content and reveal the full name on hover only
// when it's actually cut off. The tooltip prefers the explicit label but falls back to the rendered text,
// so titles rendered from JSX (e.g. a human-readable property name) show their label, not a raw column key.
function ColumnHeaderTitle({
    formattedTitle,
    fullTitle,
    description,
    truncateTitle,
    children,
}: {
    formattedTitle: React.ReactNode
    fullTitle?: string
    description?: string
    truncateTitle?: boolean
    children?: React.ReactNode
}): JSX.Element {
    const titleRef = useRef<HTMLSpanElement>(null)
    const [tooltip, setTooltip] = useState<string | undefined>(undefined)

    const detectTruncation = useCallback((): void => {
        const el = titleRef.current
        if (!el) {
            return
        }
        const isTruncated = el.scrollHeight - el.clientHeight > 1 || el.scrollWidth - el.clientWidth > 1
        setTooltip(isTruncated ? fullTitle || el.textContent || undefined : undefined)
    }, [fullTitle])

    useLayoutEffect(() => {
        detectTruncation()
    }, [detectTruncation])

    return (
        <div className={cn('flex items-center gap-1', truncateTitle && 'min-w-0')}>
            <Tooltip title={tooltip}>
                <span
                    ref={titleRef}
                    onMouseEnter={detectTruncation}
                    className={truncateTitle ? 'min-w-0 truncate' : undefined}
                >
                    {formattedTitle}
                </span>
            </Tooltip>
            {description?.trim() && (
                <Tooltip
                    title={
                        <div
                            className="ph-no-capture max-h-[min(20rem,calc(100vh-4rem))] overflow-y-auto whitespace-pre-wrap"
                            tabIndex={0}
                        >
                            {description}
                        </div>
                    }
                    openOnClick
                    interactive
                    onOpen={captureColumnDescriptionViewed}
                >
                    <LemonButton
                        className="ph-no-capture shrink-0"
                        size="xsmall"
                        noPadding
                        icon={<IconInfo />}
                        aria-label={`Description for ${fullTitle ?? 'column'}`}
                        aria-description={description}
                        onClick={(event) => event.stopPropagation()}
                    />
                </Tooltip>
            )}
            {children}
        </div>
    )
}

export const Table = (props: TableProps): JSX.Element => {
    const { isDarkModeOn } = useValues(themeLogic)

    const {
        tableRows,
        tableResults,
        getTableCell,
        getSourceTableCell,
        tabularColumns,
        sourceTabularColumns,
        conditionalFormattingRules,
        responseLoading,
        responseError,
        queryCancelled,
        response,
        pinnedColumns,
        isColumnPinned,
        isPinningEnabled,
        isTransposed,
        hasSortedTable,
        hasMoreData,
        hogVm,
        hogVmLoadFailed,
    } = useValues(dataVisualizationLogic)
    const virtualizationCellThreshold = props.context?.dataVisualizationTableVirtualizationCellThreshold ?? 0
    const virtualized =
        !!props.embedded &&
        !!props.context?.dataVisualizationTableVirtualized &&
        tableRows.length * tabularColumns.length > virtualizationCellThreshold
    const virtualizeColumns = (virtualized || isTransposed) && tabularColumns.length > 50
    const { toggleColumnPin, setTableSorted } = useActions(dataVisualizationLogic)

    // Virtualized tables use a fixed layout, which can't fit columns to cells that aren't rendered
    const columnWidths = useMemo(
        () =>
            virtualized || virtualizeColumns
                ? estimateColumnWidths(
                      tabularColumns.map(({ column, settings }) => settings?.display?.label || column.name),
                      tableRows.length,
                      (sampleRowIndex, columnIndex) => getTableCell(tableRows[sampleRowIndex].rowIndex, columnIndex)
                  )
                : undefined,
        [virtualized, virtualizeColumns, tabularColumns, tableRows, getTableCell]
    )

    const sourceTabularColumnsByName = new Map(sourceTabularColumns.map((column) => [column.column.name, column]))

    const tableColumns = tabularColumns.map<LemonTableColumn<TableRow, any>>(({ column, settings }, index) => {
        const { title, ...columnMeta } = renderColumnMeta(column.name, props.query, props.context)
        const columnTitle = settings?.display?.label || title || column.name
        const formattedTitle = typeof columnTitle === 'string' ? formatColumnTitle(columnTitle) : columnTitle
        const fullColumnTitle = typeof columnTitle === 'string' ? columnTitle : undefined

        const computeConditionalFormattingBackground = (rowIndex: number): string | undefined => {
            if (!hogVm) {
                return undefined
            }
            const cell = getTableCell(rowIndex, index)
            if (cell.isTransposedHeader) {
                return undefined
            }

            const sourceColumnName = cell.sourceColumnName ?? column.name
            const sourceColumnType = sourceTabularColumnsByName.get(sourceColumnName)?.column.type.name ?? cell.type
            return conditionalFormattingColor(
                conditionalFormattingRules,
                hogVm.execHog,
                sourceColumnName,
                sourceColumnType,
                cell.value,
                isDarkModeOn
            )
        }

        // The style and class callbacks run separately. Cache the last row to avoid a second HogVM call
        // without retaining offscreen rows. A new column closure invalidates the cache when the theme or rules change.
        let backgroundRowIndex: number | undefined
        let backgroundColor: string | undefined
        const resolveConditionalFormattingBackground = (rowIndex: number): string | undefined => {
            if (backgroundRowIndex !== rowIndex) {
                backgroundColor = computeConditionalFormattingBackground(rowIndex)
                backgroundRowIndex = rowIndex
            }
            return backgroundColor
        }

        let sortCells: TableDataCell<any>[] | undefined

        return {
            ...columnMeta,
            width: columnWidths?.[index] ?? columnMeta.width,
            key: column.name,
            // Sorting reorders rows, which doesn't make sense once the table is transposed
            // (rows become the original columns), so only offer it in the normal orientation.
            sorter: isTransposed
                ? undefined
                : (a, b) => {
                      sortCells ??= tableRows.map((row) => getTableCell(row.rowIndex, index))
                      return compareTableCells(sortCells[a.rowIndex], sortCells[b.rowIndex])
                  },
            title: (
                <ColumnHeaderTitle
                    formattedTitle={formattedTitle}
                    fullTitle={fullColumnTitle}
                    description={settings?.display?.description}
                >
                    {isPinningEnabled && (
                        <Tooltip title={isColumnPinned(column.name) ? 'Unpin column' : 'Pin column'}>
                            <span
                                className="inline-flex items-center justify-center cursor-pointer p-1 -m-1"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    toggleColumnPin(column.name)
                                }}
                            >
                                {isColumnPinned(column.name) ? (
                                    <IconPinFilled className="text-sm" />
                                ) : (
                                    <IconPin className="text-sm" />
                                )}
                            </span>
                        </Tooltip>
                    )}
                </ColumnHeaderTitle>
            ),
            render: (_, data, recordIndex: number, rowCount: number) => {
                const cell = getTableCell(data.rowIndex, index)

                if (cell.isTransposedHeader) {
                    const sourceColumnTitle = cell.sourceColumnName
                        ? getDisplayedColumnTitle(
                              cell.sourceColumnName,
                              sourceTabularColumnsByName.get(cell.sourceColumnName)?.settings?.display?.label,
                              props.query,
                              props.context
                          )
                        : cell.formattedValue
                    const renderedSourceColumnTitle =
                        typeof sourceColumnTitle === 'string'
                            ? formatColumnTitle(sourceColumnTitle)
                            : React.isValidElement(sourceColumnTitle) ||
                                sourceColumnTitle == null ||
                                typeof sourceColumnTitle === 'number'
                              ? sourceColumnTitle
                              : String(sourceColumnTitle)

                    return (
                        <div
                            className="min-w-0"
                            title={typeof sourceColumnTitle === 'string' ? sourceColumnTitle : undefined}
                        >
                            <ColumnHeaderTitle
                                truncateTitle
                                formattedTitle={renderedSourceColumnTitle}
                                fullTitle={typeof sourceColumnTitle === 'string' ? sourceColumnTitle : undefined}
                                description={
                                    cell.sourceColumnName
                                        ? sourceTabularColumnsByName.get(cell.sourceColumnName)?.settings?.display
                                              ?.description
                                        : undefined
                                }
                            />
                        </div>
                    )
                }

                if (props.onInspect) {
                    const sourceRowIndex = isTransposed ? index - 1 : data.rowIndex
                    const sourceColumns = isTransposed ? sourceTabularColumns : tabularColumns
                    return (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            // The negative margin cancels the button padding, so the value lines up with the header text
                            className="-mx-1.5 max-w-[calc(100%+0.75rem)] !text-inherit"
                            tooltip="Explore this result"
                            onClick={() =>
                                props.onInspect?.(
                                    Object.fromEntries(
                                        sourceColumns.map((column, index) => [
                                            column.column.name,
                                            getSourceTableCell(sourceRowIndex, index).value,
                                        ])
                                    )
                                )
                            }
                        >
                            <span className="truncate">{String(cell.formattedValue ?? '—')}</span>
                        </LemonButton>
                    )
                }

                return (
                    <div className="truncate" title={getCellTitle(cell)}>
                        {renderColumn(
                            cell.sourceColumnName ?? column.name,
                            cell.formattedValue,
                            tableResults[isTransposed ? index - 1 : data.rowIndex],
                            recordIndex,
                            rowCount,
                            {
                                kind: NodeKind.DataTableNode,
                                source: props.query.source,
                            }
                        )}
                    </div>
                )
            },
            style: (_, data) => {
                const backgroundColor = resolveConditionalFormattingBackground(data.rowIndex)
                return backgroundColor ? { backgroundColor } : undefined
            },
            className: (_, data) => {
                const backgroundColor = resolveConditionalFormattingBackground(data.rowIndex)
                // Pin the text color to the cell background rather than inheriting the theme's text
                // color, which is near-white in dark mode and unreadable on light backgrounds
                return backgroundColor ? getContrastingTextClass(backgroundColor) : ''
            },
        }
    })

    return (
        <>
            {hogVmLoadFailed ? (
                <LemonBanner
                    type="warning"
                    className="mb-2"
                    action={{ children: 'Reload page', onClick: () => window.location.reload() }}
                >
                    Couldn't load conditional formatting, so cells show without their colors. Reload the page to try
                    again.
                </LemonBanner>
            ) : null}
            {hasSortedTable && hasMoreData && (
                <LemonBanner type="info" className="mb-2" dismissKey="data-visual">
                    Sorting only reorders the rows already loaded, not the full dataset.
                </LemonBanner>
            )}
            <LemonTable
                className="DataVisualizationTable"
                rowKey="rowIndex"
                dataSource={tableRows}
                columns={tableColumns}
                pinnedColumns={isPinningEnabled ? pinnedColumns : undefined}
                loading={responseLoading}
                useURLForSorting={false}
                onSort={(newSorting) => {
                    if (newSorting) {
                        setTableSorted()
                    }
                }}
                pagination={{ pageSize: DEFAULT_PAGE_SIZE }}
                maxHeaderWidth="15rem"
                emptyState={
                    responseError ? (
                        <InsightErrorState
                            query={props.query}
                            excludeDetail
                            title={
                                queryCancelled
                                    ? 'The query was cancelled'
                                    : response && 'error' in response
                                      ? (response as any).error
                                      : responseError
                            }
                        />
                    ) : (
                        <InsightEmptyState
                            heading="There are no matching rows for this query"
                            detail=""
                            sampleDataVariant="table"
                        />
                    )
                }
                footer={tableRows.length > 0 ? <LoadNext query={props.query} /> : null}
                rowClassName="DataVizRow"
                embedded={props.embedded}
                allowContentScroll={!!props.embedded}
                virtualized={virtualized}
                virtualizedColumnWidth={virtualizeColumns ? 192 : undefined}
                tableLayout={virtualized ? 'fixed' : 'auto'}
                tableStyle={
                    columnWidths ? { minWidth: columnWidths.reduce((total, width) => total + width, 0) } : undefined
                }
            />
        </>
    )
}
