import '../../DataTable/DataTable.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React from 'react'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { LemonTable, LemonTableColumn, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { execHog } from 'lib/hog'
import { lightenDarkenColor } from 'lib/utils'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import {
    ConditionalFormattingRule,
    DataVisualizationNode,
    HogQLQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { LoadNext } from '../../DataNode/LoadNext'
import { renderColumn } from '../../DataTable/renderColumn'
import { renderColumnMeta } from '../../DataTable/renderColumnMeta'
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

function coerceToNumberArray(value: unknown): number[] | null {
    if (!Array.isArray(value)) {
        return null
    }
    const out: number[] = []
    for (const item of value) {
        const num = typeof item === 'number' ? item : item == null ? NaN : Number(item)
        if (!Number.isFinite(num)) {
            return null
        }
        out.push(num)
    }
    return out
}

function matchConditionalFormattingRule(
    rules: ConditionalFormattingRule[],
    sourceColumnName: string,
    cellValue: any,
    cellType: string
): ConditionalFormattingRule | undefined {
    for (const rule of rules) {
        if (rule.columnName !== sourceColumnName) {
            continue
        }
        const isValidHog = !!rule.bytecode && rule.bytecode.length > 0 && rule.bytecode[0] === '_H'
        if (!isValidHog) {
            posthog.captureException(new Error('Invalid hog bytecode for conditional formatting'), {
                formatRule: rule,
            })
            continue
        }
        const res = execHog(rule.bytecode, {
            globals: {
                value: cellValue,
                input: convertTableValue(rule.input, cellType),
            },
            functions: {},
            maxAsyncSteps: 0,
        })
        if (res.result) {
            return rule
        }
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

                        return <div className="truncate">{renderedSourceColumnTitle}</div>
                    }

                    const sourceColumnName = cell.sourceColumnName ?? column.name
                    const sourceColumnType =
                        sourceTabularColumnsByName.get(sourceColumnName)?.column.type.name ?? cell.type
                    const matchedRule = matchConditionalFormattingRule(
                        conditionalFormattingRules,
                        sourceColumnName,
                        cell.value,
                        sourceColumnType
                    )
                    const displayMode = matchedRule?.displayMode ?? 'background'

                    if (settings?.display?.renderAs === 'sparkline') {
                        const numbers = coerceToNumberArray(cell.value)
                        if (numbers === null) {
                            return (
                                <Tooltip title="Sparkline columns require an array of numbers (e.g. groupArray(value)).">
                                    <span className="text-muted italic">—</span>
                                </Tooltip>
                            )
                        }
                        const sparkline = settings.display.sparkline
                        return (
                            <Sparkline
                                data={numbers}
                                color={sparkline?.color ?? 'primary'}
                                type={sparkline?.type ?? 'line'}
                                maximumIndicator={false}
                                className="h-6 w-24"
                            />
                        )
                    }

                    const renderedCell = renderColumn(
                        sourceColumnName,
                        cell.formattedValue,
                        data,
                        recordIndex,
                        rowCount,
                        {
                            kind: NodeKind.DataTableNode,
                            source: props.query.source,
                        }
                    )

                    if (matchedRule && displayMode === 'dot') {
                        return (
                            <div className="truncate flex items-center gap-2">
                                <span
                                    aria-hidden
                                    className="inline-block w-2 h-2 rounded-full shrink-0"
                                    style={{ backgroundColor: matchedRule.color }}
                                />
                                <span className="truncate">{renderedCell}</span>
                            </div>
                        )
                    }

                    if (matchedRule && displayMode === 'badge') {
                        const badgeLabel = matchedRule.label?.trim() ? matchedRule.label : renderedCell
                        return (
                            <div className="truncate">
                                <LemonTag style={{ backgroundColor: matchedRule.color, borderColor: 'transparent' }}>
                                    {badgeLabel}
                                </LemonTag>
                            </div>
                        )
                    }

                    return <div className="truncate">{renderedCell}</div>
                },
                style: (_, data) => {
                    const cell = data[index]

                    if (cell.isTransposedHeader) {
                        return undefined
                    }

                    const sourceColumnName = cell.sourceColumnName ?? column.name
                    const sourceColumnType =
                        sourceTabularColumnsByName.get(sourceColumnName)?.column.type.name ?? cell.type
                    const matchedRule = matchConditionalFormattingRule(
                        conditionalFormattingRules,
                        sourceColumnName,
                        cell.value,
                        sourceColumnType
                    )

                    // Only the 'background' display mode (default) tints the cell. 'badge' and 'dot' are rendered
                    // inside the cell content by the render() function above.
                    if (!matchedRule || (matchedRule.displayMode ?? 'background') !== 'background') {
                        return undefined
                    }

                    const ruleColor = matchedRule.color
                    const colorMode = matchedRule.colorMode ?? 'light'

                    // If the color mode matches the current theme, return as it was saved
                    if ((colorMode === 'dark' && isDarkModeOn) || (colorMode === 'light' && !isDarkModeOn)) {
                        return {
                            backgroundColor: ruleColor,
                        }
                    }

                    // If the color mode is dark, but we're in light mode - then lighten the color
                    if (colorMode === 'dark' && !isDarkModeOn) {
                        return {
                            backgroundColor: lightenDarkenColor(ruleColor, 30),
                        }
                    }

                    // If the color mode is light, but we're in dark mode - then darken the color
                    return {
                        backgroundColor: lightenDarkenColor(ruleColor, -30),
                    }
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
                    <InsightEmptyState heading="There are no matching rows for this query" detail="" />
                )
            }
            footer={tabularData.length > 0 ? <LoadNext query={props.query} /> : null}
            rowClassName="DataVizRow"
            embedded={props.embedded}
            allowContentScroll={!!props.embedded}
        />
    )
}
