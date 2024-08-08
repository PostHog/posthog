import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionCumulativeCheckbox(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const cumulativeRetention = retentionFilter?.cumulative || false

    if (!canEditInsight) {
        return null
    }

    return (
        <LemonSwitch
            onChange={(cumulative: boolean) => {
                updateInsightFilter({ cumulative })
            }}
            checked={cumulativeRetention}
            label={<span className="font-normal">Rolling retention</span>}
            bordered
            size="small"
        />
    )
}
