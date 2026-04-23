import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ChartDisplayType } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowPieTotalFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { pieChartVizOptions } = useValues(trendsDataLogic(insightProps))
    const { updateVizSpecificOptions } = useActions(insightVizDataLogic(insightProps))

    const showTotal = !pieChartVizOptions?.hideAggregation

    return (
        <LemonSwitch
            className="px-2 py-1"
            onChange={(checked) => {
                updateVizSpecificOptions({
                    [ChartDisplayType.ActionsPie]: {
                        ...pieChartVizOptions,
                        hideAggregation: !checked,
                    },
                })
            }}
            checked={showTotal}
            label="Show total below chart"
            fullWidth
        />
    )
}
