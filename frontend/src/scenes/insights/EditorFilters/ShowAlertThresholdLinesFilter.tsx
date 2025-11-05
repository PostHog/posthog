import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ShowAlertThresholdLinesFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showAlertThresholdLines } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowAlertThresholdLines = (): void => {
        updateInsightFilter({ showAlertThresholdLines: !showAlertThresholdLines })
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={toggleShowAlertThresholdLines}
            checked={!!showAlertThresholdLines}
            label={<span className="font-normal">Show alert threshold lines</span>}
            size="small"
        />
    )
}
