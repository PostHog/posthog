import { useActions, useValues } from 'kea'

import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function IncludeIncompletePeriodFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const include = !!trendsFilter?.slopeIncludeIncompletePeriod

    return (
        <Tooltip title="The current period is still accumulating, so by default it's left out — including it can make a slope look like it's falling.">
            <LemonCheckbox
                className="p-1 px-2"
                onChange={() => updateInsightFilter({ slopeIncludeIncompletePeriod: !include })}
                checked={include}
                label={<span className="font-normal">Include current period</span>}
                size="small"
            />
        </Tooltip>
    )
}
