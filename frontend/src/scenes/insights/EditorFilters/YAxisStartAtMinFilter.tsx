import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function YAxisStartAtMinFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { yAxisStartAtMin } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={(checked) => updateInsightFilter({ yAxisStartAtMin: checked })}
            checked={!!yAxisStartAtMin}
            label={<span className="font-normal">Start y-axis at minimum</span>}
            size="small"
        />
    )
}
