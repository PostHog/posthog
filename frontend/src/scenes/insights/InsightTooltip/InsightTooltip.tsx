import './InsightTooltip.scss'
import React, { ReactNode } from 'react'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import {
    COL_CUTOFF,
    ROW_CUTOFF,
    getTooltipTitle,
    InsightTooltipProps,
    invertDataSource,
    InvertedSeriesDatum,
    SeriesDatum,
    getFormattedDate,
} from './insightTooltipUtils'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { IconHandClick } from 'lib/components/icons'
import { shortTimeZone } from 'lib/utils'
import { humanFriendlyNumber } from 'lib/utils'

export function ClickToInspectActors({
    isTruncated,
    groupTypeLabel,
}: {
    isTruncated?: boolean
    groupTypeLabel: string
}): JSX.Element {
    return (
        <div className="table-subtext">
            {isTruncated && (
                <div className="table-subtext-truncated">
                    For readability, <b>not all series are displayed</b>.<br />
                </div>
            )}
            <div className="table-subtext-click-to-inspect">
                <IconHandClick style={{ marginRight: 4, marginBottom: 2 }} />
                Click to view {groupTypeLabel}
            </div>
        </div>
    )
}

export function InsightTooltip({
    date,
    timezone = 'UTC',
    seriesData = [],
    altTitle,
    altRightTitle,
    renderSeries = (value: React.ReactNode, datum: SeriesDatum) => (
        <>
            <SeriesLetter className="mr-05" hasBreakdown={false} seriesIndex={datum?.action?.order ?? datum.id} />
            {value}
        </>
    ),
    renderCount = (value: number | React.ReactNode) => (
        <>{typeof value === 'number' ? humanFriendlyNumber(value) : value}</>
    ),
    hideColorCol = false,
    hideInspectActorsSection = false,
    forceEntitiesAsColumns = false,
    rowCutoff = ROW_CUTOFF,
    colCutoff = COL_CUTOFF,
    showHeader = true,
    groupTypeLabel = 'people',
}: InsightTooltipProps): JSX.Element {
    // If multiple entities exist (i.e., pageview + autocapture) and there is a breakdown/compare/multi-group happening, itemize entities as columns to save vertical space..
    // If only a single entity exists, itemize entity counts as rows.
    // Throw these rules out the window if `forceEntitiesAsColumns` is true
    const itemizeEntitiesAsColumns =
        forceEntitiesAsColumns ||
        ((seriesData?.length ?? 0) > 1 &&
            (seriesData?.[0]?.breakdown_value !== undefined || seriesData?.[0]?.compare_label !== undefined))

    const title: ReactNode | null =
        getTooltipTitle(seriesData, altTitle, date) ||
        `${getFormattedDate(date, seriesData?.[0]?.filter?.interval)} (${shortTimeZone(timezone)})`
    const rightTitle: ReactNode | null = getTooltipTitle(seriesData, altRightTitle, date) || null

    const renderTable = (): JSX.Element => {
        if (itemizeEntitiesAsColumns) {
            const dataSource = invertDataSource(seriesData)
            const columns: LemonTableColumns<InvertedSeriesDatum> = [
                {
                    key: 'datum',
                    className: 'datum-column',
                    title,
                    sticky: true,
                    render: function renderDatum(_, datum) {
                        return <div>{datum.datumTitle}</div>
                    },
                },
            ]
            const numDataPoints = Math.max(...dataSource.map((ds) => ds?.seriesData?.length ?? 0))
            const isTruncated = numDataPoints > colCutoff || dataSource.length > rowCutoff

            if (numDataPoints > 0) {
                const indexOfLongestSeries = dataSource.findIndex((ds) => ds?.seriesData?.length === numDataPoints)
                const truncatedCols = dataSource?.[
                    indexOfLongestSeries !== -1 ? indexOfLongestSeries : 0
                ].seriesData.slice(0, colCutoff)
                truncatedCols.forEach((seriesColumn, colIdx) => {
                    columns.push({
                        key: `series-column-data-${colIdx}`,
                        className: 'datum-counts-column',
                        align: 'right',
                        title:
                            (colIdx === 0 ? rightTitle : undefined) ||
                            (!altTitle &&
                                renderSeries(
                                    <InsightLabel
                                        className="series-column-header"
                                        action={seriesColumn.action}
                                        fallbackName={seriesColumn.label}
                                        hideBreakdown
                                        showSingleName
                                        hideCompare
                                        hideIcon
                                        allowWrap
                                    />,
                                    seriesColumn,
                                    colIdx
                                )),
                        render: function renderSeriesColumnData(_, datum) {
                            return (
                                <div className="series-data-cell">
                                    {renderCount(datum.seriesData?.[colIdx]?.count ?? 0, datum, colIdx)}
                                </div>
                            )
                        },
                    })
                })
            }

            return (
                <>
                    <LemonTable
                        dataSource={dataSource.slice(0, rowCutoff)}
                        columns={columns}
                        rowKey="id"
                        size="small"
                        uppercaseHeader={false}
                        rowRibbonColor={hideColorCol ? undefined : (datum) => datum.color || null}
                        showHeader={showHeader}
                    />
                    {!hideInspectActorsSection && (
                        <ClickToInspectActors isTruncated={isTruncated} groupTypeLabel={groupTypeLabel} />
                    )}
                </>
            )
        }

        // Itemize tooltip entities as rows
        const dataSource = [...seriesData]
        const columns: LemonTableColumn<SeriesDatum, keyof SeriesDatum | undefined>[] = []
        const isTruncated = dataSource?.length > rowCutoff

        columns.push({
            key: 'datum',
            className: 'datum-label-column',
            width: 120,
            title: <span className="no-wrap">{title}</span>,
            sticky: true,
            render: function renderDatum(_, datum, rowIdx) {
                return renderSeries(
                    <InsightLabel
                        action={datum.action}
                        fallbackName={datum.label}
                        hideBreakdown
                        showSingleName
                        hideCompare
                        hideIcon
                        allowWrap
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
            title: <span style={{ whiteSpace: 'nowrap' }}>{rightTitle ?? undefined}</span>,
            align: 'right',
            render: function renderDatum(_, datum, rowIdx) {
                return <div className="series-data-cell">{renderCount(datum?.count ?? 0, datum, rowIdx)}</div>
            },
        })

        return (
            <>
                <LemonTable
                    dataSource={dataSource.slice(0, rowCutoff)}
                    columns={columns}
                    rowKey="id"
                    size="small"
                    className="ph-no-capture"
                    uppercaseHeader={false}
                    rowRibbonColor={hideColorCol ? undefined : (datum: SeriesDatum) => datum.color || null}
                    showHeader={showHeader}
                />
                {!hideInspectActorsSection && (
                    <ClickToInspectActors isTruncated={isTruncated} groupTypeLabel={groupTypeLabel} />
                )}
            </>
        )
    }

    return renderTable()
}
