import { useActions, useValues } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

import { insightLogic } from '../insightLogic'

// Pie only — it's the one display that draws the series label on the chart itself.
export function SliceNamesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showLabelOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <DisplayOptionCheckbox
            label="Show names on slices"
            checked={!!showLabelOnSeries}
            onChange={() => {
                updateInsightFilter({ showLabelsOnSeries: !showLabelOnSeries })
            }}
        />
    )
}
