import './InsightTooltip.scss'
import React from 'react'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import {
    getFormattedDate,
    invertDataSource,
    InvertedSeriesDatum,
    SeriesDatum,
} from 'scenes/insights/InsightTooltip/insightTooltipUtils'

interface InsightTooltipProps {
    date?: string
    hideInspectActorsSection?: boolean
    seriesData?: SeriesDatum[]
}

export function InsightTooltip({
    date,
    seriesData = [],
}: // hideInspectActorsSection = true,
InsightTooltipProps): JSX.Element {
    const title = getFormattedDate(date)

    /*
     How to format each row's title depending on whether breakdown or compare exists
     Breakdown  | Y | Y | N | N
     Compare    | Y | N | Y | N
     Formatted  | Breakdown (compare) | Breakdown | Compare | Entity

     If multiple entities (i.e., pageview + autocapture), itemize entities as columns.
     If single entity, itemize entity counts as rows and make title the entity.
     */
    const itemizeEntitiesAsColumns =
        seriesData?.length > 1 && (seriesData?.[0]?.breakdown_value || seriesData?.[0]?.compare_value)

    if (itemizeEntitiesAsColumns) {
        const dataSource = invertDataSource(seriesData)
        const columns: LemonTableColumns<InvertedSeriesDatum> = []

        columns.push({
            key: 'color',
            className: 'color-column',
            width: 1,
            render: function renderColor(_, datum) {
                return <div style={{ backgroundColor: datum.color, height: 'var(--row-base-height)', width: 6 }} />
            },
        })

        columns.push({
            key: 'datum',
            title,
            render: function renderDatum(_, datum) {
                console.log('DATUM', datum)
                return <div>{datum.datumTitle}</div>
            },
        })

        if (dataSource?.[0]?.seriesData.length > 0) {
            dataSource[0].seriesData.forEach((seriesColumn, colIdx) => {
                columns.push({
                    key: `series-column-data-${colIdx}`,
                    align: 'right',
                    title: seriesColumn.action?.name,
                    render: function renderSeriesColumnData(_, datum) {
                        return <div>{datum.seriesData?.[colIdx]?.count}</div>
                    },
                })
            })
        }

        return <LemonTable dataSource={dataSource} columns={columns} rowKey="id" size="small" />
    }

    // Itemize tooltip entities as rows
    const dataSource = seriesData
    const columns: LemonTableColumns<SeriesDatum> = []

    return <LemonTable dataSource={dataSource} columns={columns} rowKey="id" size="small" />
}
