import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'
import { ChartDisplayType } from '~/types'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

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
        <DisplayOptionCheckbox
            label={display === ChartDisplayType.ActionsDonut ? 'Show total in center' : 'Show total below chart'}
            checked={showTotal}
            onChange={toggleShowTotal}
        />
    )
}
