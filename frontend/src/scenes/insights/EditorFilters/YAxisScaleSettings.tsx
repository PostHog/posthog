import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function YAxisScaleSettings(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={(checked) => updateInsightFilter({ yAxisScaleType: checked ? 'log10' : 'linear' })}
            checked={yAxisScaleType === 'log10'}
            label={<span className="font-normal">Log scale</span>}
            size="small"
        />
    )
}
