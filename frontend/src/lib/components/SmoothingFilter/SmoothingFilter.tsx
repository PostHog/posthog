import { useActions, useValues } from 'kea'

import { IconPulse } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'
import { insightVizDataLogic } from '@posthog/query-frontend/nodes/InsightViz/insightVizDataLogic'
import { trendsDataLogic } from '@posthog/query-frontend/nodes/TrendsQuery/trendsDataLogic'

import { insightLogic } from 'scenes/insights/insightLogic'

import { smoothingOptions } from './smoothings'

export function SmoothingFilter(): JSX.Element | null {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { isTrends, interval, trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!isTrends || !interval) {
        return null
    }

    const { smoothingIntervals } = trendsFilter || {}

    // Put a little icon next to the selected item
    const options = smoothingOptions[interval].map(({ value, label }) => ({
        value,
        label:
            value === smoothingIntervals ? (
                <>
                    <IconPulse className="mr-1.5 text-secondary" />
                    {label}
                </>
            ) : (
                label
            ),
        labelInMenu: label,
    }))

    if (!options.length) {
        return null
    }

    return (
        <LemonSelect
            key={interval}
            value={smoothingIntervals || 1}
            fullWidth
            onChange={(key) => {
                updateInsightFilter({
                    smoothingIntervals: key,
                })
            }}
            data-attr="smoothing-filter"
            options={options}
            size="small"
            disabledReason={editingDisabledReason}
        />
    )
}
