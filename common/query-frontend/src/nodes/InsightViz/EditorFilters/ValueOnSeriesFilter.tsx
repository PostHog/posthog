import { useActions, useValues } from 'kea'

import { insightVizDataLogic } from '@posthog/query-frontend/nodes/InsightViz/insightVizDataLogic'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightLogic } from 'scenes/insights/insightLogic'

export function ValueOnSeriesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showValuesOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={!!showValuesOnSeries}
            onChange={() => {
                updateInsightFilter({ showValuesOnSeries: !showValuesOnSeries })
            }}
            label={<span className="font-normal">Show values on series</span>}
            size="small"
        />
    )
}
