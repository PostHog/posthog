import { useValues, useActions } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from '../insightVizDataLogic'

import { LemonCheckbox } from '@posthog/lemon-ui'
import { TrendsFilterType } from '~/types'

export function ShowLegendFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const showLegend = (insightFilter as TrendsFilterType)?.show_legend
    const toggleShowLegend = (): void => {
        updateInsightFilter({ show_legend: !showLegend })
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={toggleShowLegend}
            checked={!!showLegend}
            label={<span className="font-normal">{showLegend ? 'Hide' : 'Show'} legend</span>}
            size="small"
        />
    )
}
