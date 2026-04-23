import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowMultipleYAxesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showMultipleYAxes } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSwitch
            className="px-2 py-1"
            onChange={(checked) => updateInsightFilter({ showMultipleYAxes: checked })}
            checked={!!showMultipleYAxes}
            label="Show multiple Y-axes"
            fullWidth
        />
    )
}
