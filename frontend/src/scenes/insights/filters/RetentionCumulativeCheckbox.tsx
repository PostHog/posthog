import { IconInfo } from '@posthog/icons'
import { LemonSwitch, Tooltip } from '@posthog/lemon-ui'
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
            label={
                <span className="font-normal">
                    Rolling retention
                    <Tooltip
                        title={
                            <>
                                Rolling, or unbounded, retention includes any subsequent time period, instead of only
                                the next period. For example, if a user is comes back on day 7, they are counted in all
                                previous retention periods.
                            </>
                        }
                    >
                        <IconInfo className="w-4 info-indicator" />
                    </Tooltip>
                </span>
            }
            bordered
            size="small"
        />
    )
}
