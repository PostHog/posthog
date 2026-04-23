import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function HideWeekendsFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSwitch
            className="px-2 py-1"
            onChange={(checked) => updateInsightFilter({ hideWeekends: checked })}
            checked={!!trendsFilter?.hideWeekends}
            label="Hide weekend data"
            fullWidth
        />
    )
}
