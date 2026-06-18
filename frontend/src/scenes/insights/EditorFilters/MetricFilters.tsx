import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { insightLogic } from '../insightLogic'

export function MetricGoodDirectionFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const higherIsBetter = (trendsFilter?.metricGoodDirection ?? 'up') === 'up'

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={higherIsBetter}
            onChange={() => updateInsightFilter({ metricGoodDirection: higherIsBetter ? 'down' : 'up' })}
            label={<span className="font-normal">Higher is better</span>}
            size="small"
        />
    )
}

export function MetricShowChangeFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const checked = trendsFilter?.metricShowChange ?? true

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={checked}
            onChange={() => updateInsightFilter({ metricShowChange: !checked })}
            label={<span className="font-normal">Show change</span>}
            size="small"
        />
    )
}
