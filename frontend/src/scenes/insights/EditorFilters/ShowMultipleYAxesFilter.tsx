import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowMultipleYAxesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showMultipleYAxes } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowMultipleYAxes = (): void => {
        updateInsightFilter({ showMultipleYAxes: !showMultipleYAxes })
    }

    return (
        <DisplayOptionCheckbox
            label="Show multiple Y-axes"
            checked={!!showMultipleYAxes}
            onChange={toggleShowMultipleYAxes}
        />
    )
}
