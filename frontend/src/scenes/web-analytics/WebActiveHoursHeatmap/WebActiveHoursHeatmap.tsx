import { useValues } from 'kea'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { teamLogic } from 'scenes/teamLogic'
import { CalendarHeatMap } from 'scenes/web-analytics/CalendarHeatMap/CalendarHeatMap'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    CalendarHeatmapResponse,
    EventsHeatMapColumnAggregationResult,
    EventsHeatMapDataResult,
    EventsHeatMapRowAggregationResult,
    EventsHeatMapStructuredResult,
} from '~/queries/schema/schema-general'
import { CalendarHeatmapQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

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
    query: CalendarHeatmapQuery
    context?: QueryContext
    cachedResults?: AnyResponseType
}
let uniqueNode = 0

export function WebActiveHoursHeatmap(props: WebActiveHoursHeatmapProps): JSX.Element {
    const { weekStartDay } = useValues(teamLogic)
    const [key] = useState(() => `WebActiveHoursHeatmap.${uniqueNode++}`)

    const logic = dataNodeLogic({
        query: props.query,
        key: key,
        dataNodeCollectionId: props.context?.insightProps?.dataNodeCollectionId,
        cachedResults: props.cachedResults,
    })

    const { response: _response, responseLoading, queryId } = useValues(logic)
    const response = _response as CalendarHeatmapResponse | null

    if (responseLoading || !response?.results) {
        return (
            <InsightsWrapper>
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={props.context?.insightProps ?? {}} />
            </InsightsWrapper>
        )
    }

    const data = processData(weekStartDay, response.results, HoursAbbreviated.values, rowLabels(weekStartDay))

    return (
        <CalendarHeatMap
            {...props}
            isLoading={responseLoading}
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
    results: EventsHeatMapStructuredResult,
    columnLabels: string[],
    rowLabels: string[]
): {
    matrix: number[][]
    maxOverall: number
    minOverall: number
    columnsAggregations: number[]
    rowsAggregations: number[]
    maxRowAggregation: number
    minRowAggregation: number
    maxColumnAggregation: number
    minColumnAggregation: number
    overallValue: number
} {
    const matrix: number[][] = []
    let maxOverall = 0
    let minOverall = Infinity

    // Initialize matrix
    for (let row = 0; row < rowLabels.length; row++) {
        matrix[row] = []
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

        results.data.forEach((result: EventsHeatMapDataResult) => {
            const adjustedDay = (result.row - weekStartDay + rowLabels.length) % rowLabels.length
            matrix[adjustedDay][result.column] = result.value
            maxOverall = Math.max(maxOverall, result.value)
            minOverall = Math.min(minOverall, result.value)
        })
    }

    // Calculate columns aggregations
    const columnsAggregations: number[] = Array.from({ length: columnLabels.length }, () => 0)
    if (results?.columnAggregations) {
        results.columnAggregations.forEach((result: EventsHeatMapColumnAggregationResult) => {
            columnsAggregations[result.column] = result.value
        })
    }

    // Calculate rows aggregations
    const rowsAggregations: number[] = Array.from({ length: rowLabels.length }, () => 0)
    if (results?.rowAggregations) {
        results.rowAggregations.forEach((result: EventsHeatMapRowAggregationResult) => {
            const adjustedDay = (result.row - weekStartDay + rowLabels.length) % rowLabels.length
            rowsAggregations[adjustedDay] = result.value
        })
    }

    const maxRowAggregation = Math.max(...rowsAggregations, 0)
    const minRowAggregation = Math.min(...rowsAggregations, Infinity)
    const maxColumnAggregation = Math.max(...columnsAggregations, 0)
    const minColumnAggregation = Math.min(...columnsAggregations, Infinity)
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
