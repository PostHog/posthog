import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { MovingAverageIntervalsInput } from 'scenes/insights/views/LineGraph/MovingAverageIntervalsInput'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

export function MovingAverageEditorFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter, yAxisScaleType, display } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showMovingAverage } = useValues(trendsDataLogic(insightProps))

    const isLineGraph =
        !display || display === ChartDisplayType.ActionsLineGraph || display === ChartDisplayType.ActionsAreaGraph
    const isLinearScale = !yAxisScaleType || yAxisScaleType === 'linear'

    return (
        <div className="flex flex-col">
            <LemonSwitch
                label="Show moving average"
                className="px-2 pb-2"
                fullWidth
                checked={!!showMovingAverage}
                disabledReason={
                    !isLineGraph
                        ? 'Moving average is only available for line and area graphs'
                        : !isLinearScale
                          ? 'Moving average is only supported for linear scale.'
                          : undefined
                }
                onChange={(checked) => {
                    if (isTrendsQuery(querySource)) {
                        updateQuerySource({
                            ...querySource,
                            trendsFilter: { ...trendsFilter, showMovingAverage: checked },
                        })
                    }
                }}
            />
            {showMovingAverage && <MovingAverageIntervalsInput />}
        </div>
    )
}
