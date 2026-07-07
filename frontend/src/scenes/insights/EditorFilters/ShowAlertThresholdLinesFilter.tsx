import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { InsightDisplayToggle, InsightToggleVariant } from './InsightDisplayToggle'

export function ShowAlertThresholdLinesFilter({
    variant,
}: {
    variant?: InsightToggleVariant
} = {}): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { showAlertThresholdLines } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggleShowAlertThresholdLines = (): void => {
        updateInsightFilter({ showAlertThresholdLines: !showAlertThresholdLines })
    }

    return (
        <InsightDisplayToggle
            label="Show alert threshold lines"
            onChange={toggleShowAlertThresholdLines}
            checked={!!showAlertThresholdLines}
            variant={variant}
        />
    )
}
