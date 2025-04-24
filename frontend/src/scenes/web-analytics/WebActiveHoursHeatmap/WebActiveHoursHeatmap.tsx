import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    HeatMapColumnAggregationResult,
    HeatMapDataResult,
    HeatMapRowAggregationResult,
    HeatMapStructuredResult,
} from '~/queries/schema/schema-general'
import { WebActiveHoursHeatMapQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { EventsHeatMap } from '../EventsHeatMap/EventsHeatMap'
import {
    AggregationLabel,
    getColumnAggregationTooltip,
    getDataTooltip,
    getOverallAggregationTooltip,
    getRowAggregationTooltip,
    HoursAbbreviated,
    rowLabels,
    thresholdFontSize,
} from './utils'

interface WebActiveHoursHeatmapProps {
    query: WebActiveHoursHeatMapQuery
    context: QueryContext
    cachedResults?: AnyResponseType
}

export function WebActiveHoursHeatmap(props: WebActiveHoursHeatmapProps): JSX.Element {
    const { weekStartDay } = useValues(teamLogic)

    const { response, responseLoading, queryId } = useValues(
        dataNodeLogic({
            query: props.query,
            key: 'active-hours-heatmap',
            dataNodeCollectionId: props.context.insightProps?.dataNodeCollectionId,
            cachedResults: props.cachedResults,
        })
    )

    const data = processData(weekStartDay, response?.results ?? {}, HoursAbbreviated.values, rowLabels(weekStartDay))
    return (
        <EventsHeatMap
            {...props}
            isLoading={responseLoading}
            queryId={queryId}
            thresholdFontSize={thresholdFontSize}
            rowLabels={rowLabels(weekStartDay)}
            columnLabels={HoursAbbreviated.values}
            allAggregationsLabel={AggregationLabel.All}
            processedData={data}
            getDataTooltip={getDataTooltip}
            getColumnAggregationTooltip={getColumnAggregationTooltip}
            getRowAggregationTooltip={getRowAggregationTooltip}
            getOverallAggregationTooltip={getOverallAggregationTooltip}
        />
    )
}

function processData(
    weekStartDay: number,
    results: HeatMapStructuredResult,
    columnLabels: string[],
    rowLabels: string[]
): {
    matrix: { [key: number]: { [key: number]: number } }
    maxOverall: number
    minOverall: number
    columnsAggregations: { [key: number]: number }
    rowsAggregations: { [key: number]: number }
    maxRowAggregation: number
    minRowAggregation: number
    maxColumnAggregation: number
    minColumnAggregation: number
    overallValue: number
} {
    const matrix: { [key: number]: { [key: number]: number } } = {}
    let maxOverall = 0
    let minOverall = Infinity

    // Initialize matrix
    for (let row = 0; row < rowLabels.length; row++) {
        matrix[row] = {}
        for (let column = 0; column < columnLabels.length; column++) {
            matrix[row][column] = 0
        }
    }

    // Fill matrix with data
    if (results?.data) {
        if (results.data.length === 0) {
            // edge case where there is no data
            minOverall = 0
        }

        results.data.forEach((result: HeatMapDataResult) => {
            const adjustedDay = (result.row - weekStartDay) % rowLabels.length
            matrix[adjustedDay][result.column] = result.value
            maxOverall = Math.max(maxOverall, result.value)
            minOverall = Math.min(minOverall, result.value)
        })
    }

    // Calculate columns aggregations
    const columnsAggregations: { [key: number]: number } = Array.from({ length: columnLabels.length }, () => 0)
    if (results?.columnAggregations) {
        results.columnAggregations.forEach((result: HeatMapColumnAggregationResult) => {
            columnsAggregations[result.column] = result.value
        })
    }

    // Calculate rows aggregations
    const rowsAggregations: { [key: number]: number } = Array.from({ length: rowLabels.length }, () => 0)
    if (results?.rowAggregations) {
        results.rowAggregations.forEach((result: HeatMapRowAggregationResult) => {
            const adjustedDay = (result.row - weekStartDay) % rowLabels.length
            rowsAggregations[adjustedDay] = result.value
        })
    }

    const maxRowAggregation = Math.max(...Object.values(columnsAggregations), 0)
    const minRowAggregation = Math.min(...Object.values(columnsAggregations), Infinity)
    const maxColumnAggregation = Math.max(...Object.values(rowsAggregations), 0)
    const minColumnAggregation = Math.min(...Object.values(rowsAggregations), Infinity)
    const overallValue = results?.allAggregations ?? 0

    return {
        matrix,
        maxOverall,
        minOverall,
        columnsAggregations,
        rowsAggregations,
        maxRowAggregation,
        minRowAggregation,
        maxColumnAggregation,
        minColumnAggregation,
        overallValue,
    }
}
