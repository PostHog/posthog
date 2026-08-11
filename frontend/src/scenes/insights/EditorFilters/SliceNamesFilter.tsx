import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { insightLogic } from '../insightLogic'

// Pie only — it's the one display that draws the series label on the chart itself.
export function SliceNamesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showLabelOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={!!showLabelOnSeries}
            onChange={() => {
                updateInsightFilter({ showLabelsOnSeries: !showLabelOnSeries })
            }}
            label={<span className="font-normal">Show names on slices</span>}
            size="small"
        />
    )
}
