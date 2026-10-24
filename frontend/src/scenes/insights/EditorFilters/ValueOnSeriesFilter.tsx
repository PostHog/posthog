import { useActions, useValues } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

import { insightLogic } from '../insightLogic'

export function ValueOnSeriesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showValuesOnSeries } = useValues(insightVizDataLogic(insightProps))

    return (
        <DisplayOptionCheckbox
            label="Show values on series"
            checked={!!showValuesOnSeries}
            onChange={() => {
                updateInsightFilter({ showValuesOnSeries: !showValuesOnSeries })
            }}
        />
    )
}
