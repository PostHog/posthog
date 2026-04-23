import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function LifecycleStackingFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { lifecycleFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSwitch
            className="px-2 py-1"
            checked={lifecycleFilter?.stacked ?? true}
            onChange={(checked) => updateInsightFilter({ stacked: checked })}
            label="Stack bars"
            fullWidth
        />
    )
}
