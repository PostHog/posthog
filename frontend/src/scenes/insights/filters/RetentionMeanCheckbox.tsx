import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionMeanCheckbox(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const showMean = retentionFilter?.showMean || false

    if (!canEditInsight) {
        return null
    }

    return (
        <LemonSwitch
            onChange={(showMean: boolean) => {
                updateInsightFilter({ showMean })
            }}
            checked={showMean}
            label={<span className="font-normal">Show mean across cohorts</span>}
            bordered
            size="small"
        />
    )
}
