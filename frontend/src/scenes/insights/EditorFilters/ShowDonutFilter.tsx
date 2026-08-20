import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ChartDisplayType } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowDonutFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { pieChartVizOptions } = useValues(trendsDataLogic(insightProps))
    const { updateVizSpecificOptions } = useActions(insightVizDataLogic(insightProps))

    const donut = !!pieChartVizOptions?.donut

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={() => {
                updateVizSpecificOptions({
                    [ChartDisplayType.ActionsPie]: { ...pieChartVizOptions, donut: !donut },
                })
            }}
            checked={donut}
            label={<span className="font-normal">Donut</span>}
            size="small"
        />
    )
}
