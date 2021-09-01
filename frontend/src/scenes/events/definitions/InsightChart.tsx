import { useValues } from 'kea'
import { Loading } from 'lib/utils'
import React from 'react'
import { LineGraphEmptyState } from 'scenes/insights/EmptyStates'
import { LineGraph } from 'scenes/insights/LineGraph'
import { definitionDrawerLogic } from './definitionDrawerLogic'

export function InsightChart(): JSX.Element {
    const { graphResults, visibilityMap } = useValues(definitionDrawerLogic)
    const color = 'white'
    const inSharedMode = false
    return graphResults.length > 0 ? (
        graphResults.filter((result) => result.count !== 0).length > 0 ? (
            <LineGraph
                data-attr="trend-line-graph"
                type={'line'}
                color={color}
                datasets={graphResults}
                visibilityMap={visibilityMap}
                labels={(graphResults[0] && graphResults[0].labels) || []}
                isInProgress={false}
                dashboardItemId={null}
                inSharedMode={inSharedMode}
            />
        ) : (
            <LineGraphEmptyState color={color} isDashboard={false} />
        )
    ) : (
        <Loading />
    )
}
