import { useActions, useValues } from 'kea'

import { ChartOptionSelect } from 'lib/components/ChartOptions/ChartOptionSelect'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import { smoothingOptions } from './smoothings'

export function SmoothingFilter(): JSX.Element | null {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { isTrends, interval, trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!isTrends || !interval || !smoothingOptions[interval].length) {
        return null
    }

    return (
        <ChartOptionSelect
            key={interval}
            label="Smoothing"
            value={trendsFilter?.smoothingIntervals || 1}
            options={smoothingOptions[interval]}
            onChange={(smoothingIntervals) => updateInsightFilter({ smoothingIntervals })}
            disabledReason={editingDisabledReason}
            data-attr="smoothing-filter"
        />
    )
}
