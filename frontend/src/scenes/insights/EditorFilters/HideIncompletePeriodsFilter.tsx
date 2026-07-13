import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function HideIncompletePeriodsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { dateRange } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange } = useActions(insightVizDataLogic(insightProps))

    const excludeIncompletePeriods = dateRange?.excludeIncompletePeriods ?? false

    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={() =>
                updateDateRange(
                    {
                        excludeIncompletePeriods: !excludeIncompletePeriods,
                    },
                    true
                )
            }
            checked={excludeIncompletePeriods}
            label={
                <span className="font-normal inline-flex items-center gap-1">
                    Hide incomplete periods
                    <Tooltip title="Hides the current incomplete period from the trend.">
                        <IconInfo className="relative top-0.5 text-base text-secondary" />
                    </Tooltip>
                </span>
            }
            size="small"
        />
    )
}
