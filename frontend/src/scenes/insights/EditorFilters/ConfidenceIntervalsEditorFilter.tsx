import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { ConfidenceLevelInput } from 'scenes/insights/views/LineGraph/ConfidenceLevelInput'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

export function ConfidenceIntervalsEditorFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter, yAxisScaleType, display } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))

    const isLineGraph =
        !display || display === ChartDisplayType.ActionsLineGraph || display === ChartDisplayType.ActionsAreaGraph
    const isLinearScale = !yAxisScaleType || yAxisScaleType === 'linear'

    return (
        <div className="flex flex-col">
            <LemonSwitch
                label="Show confidence intervals"
                className="px-2 pb-2"
                fullWidth
                checked={!!showConfidenceIntervals}
                disabledReason={
                    !isLineGraph
                        ? 'Confidence intervals are only available for line graphs'
                        : !isLinearScale
                          ? 'Confidence intervals are only supported for linear scale.'
                          : undefined
                }
                onChange={(checked) => {
                    if (isTrendsQuery(querySource)) {
                        updateQuerySource({
                            ...querySource,
                            trendsFilter: { ...trendsFilter, showConfidenceIntervals: checked },
                        })
                    }
                }}
            />
            {showConfidenceIntervals && <ConfidenceLevelInput />}
        </div>
    )
}
