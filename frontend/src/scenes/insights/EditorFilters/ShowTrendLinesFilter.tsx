import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowTrendLinesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter, yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    // Get the current state based on query type
    const showTrendLines =
        isRetentionQuery(querySource) || isTrendsQuery(querySource) ? querySource.showTrendLines : false

    // Determine if trend lines should be disabled based on chart type and scale
    const isLinearScale = !yAxisScaleType || yAxisScaleType === 'linear'
    const isLineGraph = isTrendsQuery(querySource)
        ? (trendsFilter?.display || ChartDisplayType.ActionsLineGraph) === ChartDisplayType.ActionsLineGraph ||
          (trendsFilter?.display || ChartDisplayType.ActionsLineGraph) === ChartDisplayType.ActionsLineGraphCumulative
        : true // Retention graphs are always line graphs

    const disabledReason = !isLineGraph
        ? 'Trend lines are only available for line graphs'
        : !isLinearScale
        ? 'Trend lines are only supported for linear scale.'
        : undefined

    const toggleShowTrendLines = (): void => {
        updateQuerySource({ showTrendLines: !showTrendLines } as any)
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={toggleShowTrendLines}
            checked={!disabledReason && !!showTrendLines}
            disabledReason={disabledReason}
            label={<span className="font-normal">Show trend lines</span>}
            size="small"
        />
    )
}
