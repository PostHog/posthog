import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowLegendFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showLegend } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSwitch
            className="px-2 py-1"
            onChange={(checked) => updateInsightFilter({ showLegend: checked })}
            checked={!!showLegend}
            label="Show legend"
            fullWidth
        />
    )
}
