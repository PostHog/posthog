import './InsightTooltip.scss'
import React from 'react'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import {
    getFormattedDate,
    invertDataSource,
    InvertedSeriesDatum,
    SeriesDatum,
} from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { InsightLabel } from 'lib/components/InsightLabel'

interface InsightTooltipProps {
    date?: string
    hideInspectActorsSection?: boolean
    seriesData?: SeriesDatum[]
    useAltTitle?: string
}

const COL_CUTOFF = 4
const ROW_CUTOFF = 8

function ClickToInspectActors({ isTruncated }: { isTruncated: boolean }): JSX.Element {
    return (
        <div className="table-subtext">
            {isTruncated && (
                <>
                    For readability, <b>not all series are displayed</b>.<br />
                </>
            )}
            <div className="table-subtext-click-to-inspect">Click to view users</div>
        </div>
    )
}

export function InsightTooltip({ date, seriesData = [], useAltTitle }: InsightTooltipProps): JSX.Element {
    /*
     How to format each row's title depending on whether breakdown or compare exists
     Breakdown  | Y | Y | N | N
     Compare    | Y | N | Y | N
     Formatted  | Breakdown (compare) | Breakdown | Compare | Entity

     If multiple entities (i.e., pageview + autocapture), itemize entities as columns.
     If single entity, itemize entity counts as rows and make title the entity.
     */
    const formattedDate = getFormattedDate(date)
    const itemizeEntitiesAsColumns =
        seriesData?.length > 1 && (seriesData?.[0]?.breakdown_value || seriesData?.[0]?.compare_label)

    const renderTable = (): JSX.Element => {
        if (itemizeEntitiesAsColumns) {
            const dataSource = invertDataSource(seriesData)
            const columns: LemonTableColumns<InvertedSeriesDatum> = []
            const numDataPoints = Math.max(...dataSource.map((ds) => ds?.seriesData?.length ?? 0))
            const isTruncated = numDataPoints > COL_CUTOFF || dataSource.length > ROW_CUTOFF

            columns.push({
                key: 'color',
                className: 'color-column',
                width: 6,
                sticky: true,
                render: function renderColor(_, datum) {
                    return <div className="color-cell" style={{ backgroundColor: datum.color }} />
                },
            })

            columns.push({
                key: 'datum',
                className: 'datum-column',
                title: useAltTitle ?? formattedDate,
                sticky: true,
                render: function renderDatum(_, datum) {
                    return <div>{datum.datumTitle}</div>
                },
            })

            if (numDataPoints > 0) {
                const indexOfLongestSeries = dataSource.findIndex((ds) => ds?.seriesData?.length === numDataPoints)
                const truncatedCols = dataSource?.[
                    indexOfLongestSeries !== -1 ? indexOfLongestSeries : 0
                ].seriesData.slice(0, COL_CUTOFF)
                truncatedCols.forEach((seriesColumn, colIdx) => {
                    columns.push({
                        key: `series-column-data-${colIdx}`,
                        align: 'right',
                        title: (
                            <InsightLabel
                                className="series-column-header"
                                action={seriesColumn.action}
                                hideBreakdown
                                hideCompare
                                hideIcon
                                allowWrap
                            />
                        ),
                        render: function renderSeriesColumnData(_, datum) {
                            return <div className="series-data-cell">{datum.seriesData?.[colIdx]?.count ?? 0}</div>
                        },
                    })
                })
            }

            return (
                <>
                    <LemonTable
                        dataSource={dataSource.slice(0, ROW_CUTOFF)}
                        columns={columns}
                        rowKey="id"
                        size="small"
                    />
                    <ClickToInspectActors isTruncated={isTruncated} />
                </>
            )
        }

        // Itemize tooltip entities as rows
        const dataSource = seriesData
        const columns: LemonTableColumns<SeriesDatum> = []
        const isTruncated = dataSource?.length > ROW_CUTOFF

        columns.push({
            key: 'color',
            className: 'color-column',
            sticky: true,
            width: 6,
            render: function renderColor(_, datum) {
                return <div className="color-cell" style={{ backgroundColor: datum.color }} />
            },
        })

        columns.push({
            key: 'datum',
            className: 'datum-label-column',
            width: 120,
            title: useAltTitle ?? formattedDate,
            sticky: true,
            render: function renderDatum(_, datum) {
                return <InsightLabel action={datum.action} hideBreakdown hideCompare hideIcon allowWrap />
            },
        })

        columns.push({
            key: 'counts',
            className: 'datum-counts-column',
            width: 50,
            align: 'right',
            render: function renderDatum(_, datum) {
                return <div className="series-data-cell">{datum.count ?? 0}</div>
            },
        })

        return (
            <>
                <LemonTable dataSource={dataSource.slice(0, ROW_CUTOFF)} columns={columns} rowKey="id" size="small" />
                <ClickToInspectActors isTruncated={isTruncated} />
            </>
        )
    }

    return renderTable()
}
