import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowMultipleYAxesFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showMultipleYAxes } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowMultipleYAxes = (): void => {
        updateInsightFilter({ showMultipleYAxes: !showMultipleYAxes })
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={toggleShowMultipleYAxes}
            checked={!!showMultipleYAxes}
            label={<span className="font-normal">Show multiple Y-axes</span>}
            size="small"
        />
    )
}
