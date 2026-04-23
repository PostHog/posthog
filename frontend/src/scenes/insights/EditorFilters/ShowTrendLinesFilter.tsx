import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { isFunnelsQuery, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowTrendLinesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter, yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const { isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const showTrendLines = isRetentionQuery(querySource)
        ? querySource.retentionFilter.showTrendLines
        : isTrendsQuery(querySource)
          ? querySource.trendsFilter?.showTrendLines
          : isFunnelsQuery(querySource)
            ? querySource.funnelsFilter?.showTrendLines
            : false

    const isLinearScale = !yAxisScaleType || yAxisScaleType === 'linear'
    const isLineGraph = isTrendsQuery(querySource)
        ? (trendsFilter?.display || ChartDisplayType.ActionsLineGraph) === ChartDisplayType.ActionsLineGraph ||
          (trendsFilter?.display || ChartDisplayType.ActionsLineGraph) === ChartDisplayType.ActionsLineGraphCumulative
        : isFunnelsQuery(querySource)
          ? isTrendsFunnel
          : true

    const disabledReason = !isLineGraph
        ? 'Trend lines are only available for line graphs'
        : !isLinearScale
          ? 'Trend lines are only supported for linear scale.'
          : undefined

    const toggleShowTrendLines = (): void => {
        if (isRetentionQuery(querySource)) {
            updateQuerySource({
                retentionFilter: { ...querySource.retentionFilter, showTrendLines: !showTrendLines },
            } as any)
        } else if (isTrendsQuery(querySource)) {
            updateQuerySource({ trendsFilter: { ...querySource.trendsFilter, showTrendLines: !showTrendLines } } as any)
        } else if (isFunnelsQuery(querySource)) {
            updateQuerySource({
                funnelsFilter: { ...querySource.funnelsFilter, showTrendLines: !showTrendLines },
            } as any)
        }
    }

    return (
        <LemonSwitch
            className="px-2 py-1"
            onChange={() => toggleShowTrendLines()}
            checked={!disabledReason && !!showTrendLines}
            disabledReason={disabledReason}
            label="Show trend lines"
            fullWidth
        />
    )
}
