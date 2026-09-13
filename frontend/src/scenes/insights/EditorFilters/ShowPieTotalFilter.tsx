import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ChartDisplayType } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowPieTotalFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { display, pieChartVizOptions } = useValues(trendsDataLogic(insightProps))
    const { updateVizSpecificOptions } = useActions(insightVizDataLogic(insightProps))

    const showTotal = !pieChartVizOptions?.hideAggregation

    const toggleShowTotal = (): void => {
        updateVizSpecificOptions({
            // Donut stores its options under the pie key too, so the setting survives switching between them.
            [ChartDisplayType.ActionsPie]: {
                ...pieChartVizOptions,
                hideAggregation: showTotal,
            },
        })
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={toggleShowTotal}
            checked={showTotal}
            label={
                <span className="font-normal">
                    {display === ChartDisplayType.ActionsDonut ? 'Show total in center' : 'Show total below chart'}
                </span>
            }
            size="small"
        />
    )
}
