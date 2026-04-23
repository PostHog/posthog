import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { insightLogic } from '../insightLogic'

export function ValueOnSeriesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showValuesOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <LemonSwitch
            className="px-2 py-1"
            checked={!!showValuesOnSeries}
            onChange={(checked) => updateInsightFilter({ showValuesOnSeries: checked })}
            label="Show values on series"
            fullWidth
        />
    )
}
