import './InsightTooltip.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { ReactNode } from 'react'

import { IconX } from '@posthog/icons'

import { InsightLabel } from 'lib/components/InsightLabel'
import { dayjs } from 'lib/dayjs'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { shortTimeZone } from 'lib/utils/timezones'
import { formatAggregationValue } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'

import { FormatPropertyValueForDisplayFunction, propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import {
    InsightTooltipProps,
    InvertedSeriesDatum,
    SeriesDatum,
    getFormattedDate,
    getTooltipTitle,
    invertDataSource,
} from './insightTooltipUtils'

export function ClickToInspectActors({
    inspectLabel,
    groupTypeLabel,
    showShiftKeyHint,
}: {
    inspectLabel?: string
    groupTypeLabel: string
    showShiftKeyHint?: boolean
}): JSX.Element {
    return (
        <div className="table-subtext">
            {showShiftKeyHint && (
                <>
                    <div>Hold Shift (⇧) to highlight individual bars</div>
                    <br />
                </>
            )}
            <div className="table-subtext-click-to-inspect">{inspectLabel ?? `Click to view ${groupTypeLabel}`}</div>
        </div>
    )
}

function renderDatumToTableCell(
    datumMathProperty: string | undefined | null,
    datumValue: number | undefined,
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction,
    renderCount: (value: number) => React.ReactNode,
    /** Optional hexadecimal color string.
     * Usually the color is shown on the datum row level, but in case of breakdowns where there are multiple columns,
     * we need to show the color separately for each cell.
     */
    color?: string
): JSX.Element {
    // Value can be undefined if the datum's series doesn't have ANY value for the breakdown value being rendered
    return (
        <div className="series-data-cell">
            {color && (
                // eslint-disable-next-line react/forbid-dom-props
                <span className="mr-2" style={{ color }}>
                    ●
                </span>
            )}
            {datumValue !== undefined
                ? formatAggregationValue(datumMathProperty, datumValue, renderCount, formatPropertyValueForDisplay)
                : '–'}
        </div>
    )
}

function closeColumn<T extends Record<string, any>>(onClose: () => void): LemonTableColumn<T, keyof T | undefined> {
    return {
        key: 'close',
        className: 'InsightTooltip__close-column',
        width: 0,
        title: (
            <button
                type="button"
                className="InsightTooltip__close p-0.5 ml-2 rounded hover:bg-fill-button-tertiary-hover cursor-pointer"
                onClick={onClose}
            >
                <IconX className="w-3 h-3" />
            </button>
        ),
        render: () => null,
    }
}

export function InsightTooltip({
    date,
    timezone = 'UTC',
    seriesData = [],
    altTitle,
    altRightTitle,
    renderSeries,
    renderCount,
    embedded = false,
    hideColorCol = false,
    hideInspectActorsSection = false,
    rowCutoff,
    colCutoff,
    showHeader = true,
    inspectLabel,
    groupTypeLabel = 'people',
    breakdownFilter,
    interval,
    dateRange,
    showShiftKeyHint,
    formatCompareLabel,
    onClose,
    onRowClick,
}: InsightTooltipProps): JSX.Element {
    // Display entities as columns if multiple exist (e.g., pageview + autocapture, or multiple formulas)
    // and the insight has a breakdown or compare option enabled. This gives us space for labels
    // in the first column of each row.
    const itemizeEntitiesAsColumns =
        (seriesData?.length ?? 0) > 1 &&
        (seriesData?.[0]?.breakdown_value !== undefined || seriesData?.[0]?.compare_label !== undefined)

    const hasMultipleDatapoints = (seriesData?.length ?? 0) > 1
    const defaultInspectLabel = hasMultipleDatapoints
        ? `Click a series above to view ${groupTypeLabel}`
        : `Click to view ${groupTypeLabel}`

    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { weekStartDay } = useValues(teamLogic)
    const formattedDate = getFormattedDate(date, {
        interval,
        dateRange,
        timezone,
        weekStartDay,
    })

    const shortFormattedDate = getFormattedDate(date, {
        interval,
        dateRange,
        timezone,
        weekStartDay,
        short: true,
    })

    const concreteTooltipTitle = altTitle ? getTooltipTitle(seriesData, altTitle, formattedDate) : null

    const fullDateTitle = date
        ? `${interval === 'day' ? `${dayjs.tz(date, timezone).format('dddd')}, ` : ''}${formattedDate} (${timezone ? shortTimeZone(timezone) : 'UTC'})`
        : null

    const title: ReactNode | null =
        concreteTooltipTitle ||
        (date ? (
            // Only the column-per-entity layout is width-constrained enough to need the date shortened.
            itemizeEntitiesAsColumns ? (
                <Tooltip title={fullDateTitle}>
                    <span>{shortFormattedDate}</span>
                </Tooltip>
            ) : (
                fullDateTitle
            )
        ) : null)
    const rightTitle: ReactNode | null = altRightTitle
        ? getTooltipTitle(seriesData, altRightTitle, formattedDate)
        : null

    if (itemizeEntitiesAsColumns) {
        hideColorCol = true
        const dataSource = invertDataSource(seriesData, breakdownFilter, formatCompareLabel)
        const columns: LemonTableColumns<InvertedSeriesDatum> = [
            {
                key: 'datum',
                className: 'datum-column',
                title,
                sticky: true,
                render: function renderDatum(_, datum) {
                    return <div className="datum-title">{datum.datumTitle}</div>
                },
            },
        ]
        const numDataPoints = Math.max(...dataSource.map((ds) => ds?.seriesData?.length ?? 0))

        if (numDataPoints === 1) {
            // Each row holds one series; breaking multiple series down by event name gives them
            // distinct `order`s, so an order-keyed column would blank every non-matching row.
            columns.push({
                key: 'value',
                className: 'datum-counts-column',
                align: 'right',
                title: <span className="whitespace-nowrap">{rightTitle ?? undefined}</span>,
                render: function renderSingleSeriesValue(_, datum) {
                    const seriesColumnData = datum.seriesData[0]
                    return renderDatumToTableCell(
                        seriesColumnData?.action?.math_property,
                        seriesColumnData?.count,
                        formatPropertyValueForDisplay,
                        renderCount,
                        seriesColumnData?.color
                    )
                },
            })
        } else if (numDataPoints > 1) {
            // Key columns off the union of orders across all rows, not just the longest one, so a
            // series present in only some rows still gets a column instead of a dash.
            const seriesByOrder = new Map<number, SeriesDatum>()
            for (const ds of dataSource) {
                for (const s of ds?.seriesData ?? []) {
                    if (!seriesByOrder.has(s.order)) {
                        seriesByOrder.set(s.order, s)
                    }
                }
            }
            const sortedColumnSeries = [...seriesByOrder.values()].sort((a, b) => a.order - b.order)
            const truncatedCols = colCutoff !== undefined ? sortedColumnSeries.slice(0, colCutoff) : sortedColumnSeries
            const dataColumns: LemonTableColumn<InvertedSeriesDatum, keyof InvertedSeriesDatum | undefined>[] = []
            truncatedCols.forEach((seriesColumn) => {
                const colIdx = seriesColumn.order
                dataColumns.push({
                    key: colIdx.toString(),
                    className: 'datum-counts-column',
                    align: 'right',
                    title:
                        (colIdx === 0 ? rightTitle : undefined) ||
                        (!concreteTooltipTitle &&
                            renderSeries(
                                <InsightLabel
                                    action={seriesColumn.action}
                                    fallbackName={seriesColumn.label}
                                    showSingleName
                                    hideBreakdown
                                    hideCompare
                                    hideIcon
                                />,
                                seriesColumn,
                                colIdx
                            )),
                    render: function renderSeriesColumnData(_, datum) {
                        const seriesColumnData: SeriesDatum | undefined = datum.seriesData.find(
                            (s) => s.order === colIdx
                        )
                        const cell = renderDatumToTableCell(
                            seriesColumnData?.action?.math_property,
                            seriesColumnData?.count,
                            formatPropertyValueForDisplay,
                            renderCount,
                            seriesColumnData?.color
                        )
                        if (onRowClick && seriesColumnData) {
                            return (
                                <div
                                    className="cursor-pointer hover:bg-accent-highlight-secondary -mx-2 px-2 -my-1 py-1"
                                    onClick={() => onRowClick(seriesColumnData)}
                                >
                                    {cell}
                                </div>
                            )
                        }
                        return cell
                    },
                })
            })
            columns.push(...dataColumns)
        }

        if (onClose) {
            columns.push(closeColumn(onClose))
        }

        return (
            <div className={clsx('InsightTooltip', embedded && 'InsightTooltip--embedded')} data-attr="insight-tooltip">
                <div className="InsightTooltip__scrollable">
                    <LemonTable
                        dataSource={rowCutoff !== undefined ? dataSource.slice(0, rowCutoff) : dataSource}
                        columns={columns}
                        rowKey="id"
                        uppercaseHeader={false}
                        rowRibbonColor={hideColorCol ? undefined : (datum) => datum.color || null}
                        showHeader={showHeader}
                        onRow={
                            onRowClick && numDataPoints === 1
                                ? (datum) => ({
                                      onClick: () => {
                                          const seriesDatum = datum.seriesData[0]
                                          if (seriesDatum) {
                                              onRowClick(seriesDatum)
                                          }
                                      },
                                  })
                                : undefined
                        }
                    />
                </div>
                {!hideInspectActorsSection && (
                    <ClickToInspectActors
                        inspectLabel={inspectLabel ?? defaultInspectLabel}
                        groupTypeLabel={groupTypeLabel}
                        showShiftKeyHint={showShiftKeyHint}
                    />
                )}
            </div>
        )
    }

    // Itemize tooltip entities as rows
    const dataSource = [...seriesData]
    const columns: LemonTableColumn<SeriesDatum, keyof SeriesDatum | undefined>[] = []

    columns.push({
        key: 'datum',
        className: 'datum-column',
        width: 200,
        title: <span className="whitespace-nowrap">{title}</span>,
        sticky: true,
        render: function renderDatum(_, datum, rowIdx) {
            return renderSeries(
                <InsightLabel
                    action={datum.action}
                    fallbackName={datum.label}
                    showSingleName
                    hideBreakdown
                    hideCompare
                    hideIcon
                />,
                datum,
                rowIdx
            )
        },
    })

    columns.push({
        key: 'counts',
        className: 'datum-counts-column',
        width: 50,
        title: <span className="whitespace-nowrap">{rightTitle ?? undefined}</span>,
        align: 'right',
        render: function renderDatum(_, datum) {
            return (
                <div>
                    {renderDatumToTableCell(
                        datum.action?.math_property,
                        datum.count,
                        formatPropertyValueForDisplay,
                        renderCount
                    )}
                    {datum.anomalyScore != null && (
                        <span className="ml-1 text-xs font-semibold text-danger whitespace-nowrap">
                            Anomaly: {Math.round(datum.anomalyScore * 100)}%
                        </span>
                    )}
                </div>
            )
        },
    })

    if (onClose) {
        columns.push(closeColumn(onClose))
    }

    return (
        <div className={clsx('InsightTooltip', embedded && 'InsightTooltip--embedded')} data-attr="insight-tooltip">
            <div className="InsightTooltip__scrollable">
                <LemonTable
                    dataSource={rowCutoff !== undefined ? dataSource.slice(0, rowCutoff) : dataSource}
                    columns={columns}
                    rowKey="id"
                    uppercaseHeader={false}
                    rowRibbonColor={hideColorCol ? undefined : (datum: SeriesDatum) => datum.color || null}
                    showHeader={showHeader}
                    onRow={
                        onRowClick
                            ? (datum) => ({
                                  onClick: () => onRowClick(datum),
                              })
                            : undefined
                    }
                />
            </div>
            {!hideInspectActorsSection && (
                <ClickToInspectActors
                    inspectLabel={inspectLabel ?? defaultInspectLabel}
                    groupTypeLabel={groupTypeLabel}
                    showShiftKeyHint={showShiftKeyHint}
                />
            )}
        </div>
    )
}
