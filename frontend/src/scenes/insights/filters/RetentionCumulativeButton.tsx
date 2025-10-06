import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionCumulativeButton(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const cumulativeRetention = retentionFilter?.cumulative || false

    if (!canEditInsight) {
        return null
    }

    return (
        <LemonSegmentedButton
            value={cumulativeRetention ? 1 : 0}
            onChange={(value: number) => {
                updateInsightFilter({ cumulative: value === 1 })
            }}
            options={[
                {
                    value: 0,
                    label: 'on',
                    tooltip: 'Retention value is the percentage of users who come back on a specific period',
                },
                {
                    value: 1,
                    label: 'on or after',
                    tooltip: `
                    Retention value is the percentage of users who come back on a specific time period or any of the following time periods.
                    Also known as rolling, or unbounded retention.
                    For example, if a user comes back on day 7, they are counted in all previous retention periods.`,
                },
            ]}
        />
    )
}
