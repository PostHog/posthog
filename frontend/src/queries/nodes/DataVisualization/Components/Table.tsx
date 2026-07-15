import '../../DataTable/DataTable.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React from 'react'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { LemonTable, LemonTableColumn, Tooltip } from '@posthog/lemon-ui'

import { execHog } from 'lib/hog'
import { lightenDarkenColor } from 'lib/utils/colors'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { LoadNext } from '../../DataNode/LoadNext'
import { renderColumn } from '../../DataTable/renderColumn'
import { renderColumnMeta } from '../../DataTable/renderColumnMeta'
import { getContrastingTextClass } from '../colorUtils'
import { TableDataCell, convertTableValue, dataVisualizationLogic } from '../dataVisualizationLogic'

interface TableProps {
    query: DataVisualizationNode
    uniqueKey: string | number | undefined
    context: QueryContext<DataVisualizationNode> | undefined
    cachedResults: HogQLQueryResponse | undefined
    embedded?: boolean
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
    query: DataVisualizationNode,
    context: QueryContext<DataVisualizationNode> | undefined
): React.ReactNode {
    const { title } = renderColumnMeta(columnName, query, context)
    return label || title || columnName
}

// Plain-text representation of a cell, used as the hover title so clipped content is
// still visible on hover. The full value stays in the DOM (CSS ellipsis only), so
// selecting and copying a cell copies the whole value, not just the clipped portion.
function getCellTitle(cell: TableDataCell<any>): string | undefined {
    if (typeof cell.formattedValue === 'string') {
        return cell.formattedValue
    }
    if (typeof cell.value === 'string' || typeof cell.value === 'number') {
        return String(cell.value)
    }
    return undefined
}

export const Table = (props: TableProps): JSX.Element => {
    const { isDarkModeOn } = useValues(themeLogic)

    const {
        tabularData,
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
    } = useValues(dataVisualizationLogic)
    const { toggleColumnPin } = useActions(dataVisualizationLogic)

    const sourceTabularColumnsByName = new Map(sourceTabularColumns.map((column) => [column.column.name, column]))

    const tableColumns: LemonTableColumn<TableDataCell<any>[], any>[] = tabularColumns.map(
        ({ column, settings }, index) => {
            const { title, ...columnMeta } = renderColumnMeta(column.name, props.query, props.context)
            const columnTitle = settings?.display?.label || title || column.name
            const formattedTitle = typeof columnTitle === 'string' ? formatColumnTitle(columnTitle) : columnTitle

            const computeConditionalFormattingBackground = (data: TableDataCell<any>[]): string | undefined => {
                const cell = data[index]

                if (cell.isTransposedHeader) {
                    return undefined
                }

                const sourceColumnName = cell.sourceColumnName ?? column.name
                const sourceColumnType = sourceTabularColumnsByName.get(sourceColumnName)?.column.type.name ?? cell.type
                const conditionalFormattingMatches = conditionalFormattingRules
                    .filter((n) => n.columnName === sourceColumnName)
                    .filter((n) => {
                        const isValidHog = !!n.bytecode && n.bytecode.length > 0 && n.bytecode[0] === '_H'
                        if (!isValidHog) {
                            posthog.captureException(new Error('Invalid hog bytecode for conditional formatting'), {
                                formatRule: n,
                            })
                        }

                        return isValidHog
                    })
                    .map((n) => ({
                        rule: n,
                        result: execHog(n.bytecode, {
                            globals: {
                                value: cell.value,
                                input: convertTableValue(n.input, sourceColumnType),
                            },
                            functions: {},
                            maxAsyncSteps: 0,
                        }).result,
                    }))
                    .find((n) => Boolean(n.result))

                if (!conditionalFormattingMatches) {
                    return undefined
                }

                const ruleColor = conditionalFormattingMatches.rule.color
                const colorMode = conditionalFormattingMatches.rule.colorMode ?? 'light'

                // If the color mode matches the current theme, use the color as it was saved
                if ((colorMode === 'dark' && isDarkModeOn) || (colorMode === 'light' && !isDarkModeOn)) {
                    return ruleColor
                }

                // If the color mode is dark, but we're in light mode - then lighten the color
                if (colorMode === 'dark' && !isDarkModeOn) {
                    return lightenDarkenColor(ruleColor, 30)
                }

                // If the color mode is light, but we're in dark mode - then darken the color
                return lightenDarkenColor(ruleColor, -30)
            }

            // The `style` and `className` cell callbacks are invoked independently for the same cell,
            // so memoize per row record to run the HogVM rules (and any captureException) only once.
            // The cache lives in this per-render closure, so it can't go stale across theme/rule changes.
            const backgroundByRecord = new WeakMap<TableDataCell<any>[], string | undefined>()
            const resolveConditionalFormattingBackground = (data: TableDataCell<any>[]): string | undefined => {
                if (backgroundByRecord.has(data)) {
                    return backgroundByRecord.get(data)
                }
                const backgroundColor = computeConditionalFormattingBackground(data)
                backgroundByRecord.set(data, backgroundColor)
                return backgroundColor
            }

            return {
                ...columnMeta,
                key: column.name,
                title: (
                    <div className="flex items-center gap-1">
                        <span>{formattedTitle}</span>
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
                    </div>
                ),
                render: (_, data, recordIndex: number, rowCount: number) => {
                    const cell = data[index]

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
                                className="truncate"
                                title={typeof sourceColumnTitle === 'string' ? sourceColumnTitle : undefined}
                            >
                                {renderedSourceColumnTitle}
                            </div>
                        )
                    }

                    return (
                        <div className="truncate" title={getCellTitle(cell)}>
                            {renderColumn(
                                cell.sourceColumnName ?? column.name,
                                cell.formattedValue,
                                data,
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
                    const backgroundColor = resolveConditionalFormattingBackground(data)
                    return backgroundColor ? { backgroundColor } : undefined
                },
                className: (_, data) => {
                    const backgroundColor = resolveConditionalFormattingBackground(data)
                    // Pin the text color to the cell background rather than inheriting the theme's text
                    // color, which is near-white in dark mode and unreadable on light backgrounds
                    return backgroundColor ? getContrastingTextClass(backgroundColor) : ''
                },
            }
        }
    )

    return (
        <LemonTable
            className="DataVisualizationTable"
            dataSource={tabularData}
            columns={tableColumns}
            pinnedColumns={isPinningEnabled ? pinnedColumns : undefined}
            loading={responseLoading}
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
            footer={tabularData.length > 0 ? <LoadNext query={props.query} /> : null}
            rowClassName="DataVizRow"
            embedded={props.embedded}
            allowContentScroll={!!props.embedded}
        />
    )
}
