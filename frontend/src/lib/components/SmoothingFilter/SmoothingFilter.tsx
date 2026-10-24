import { useActions, useValues } from 'kea'

import { IconPulse } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { QuillDisplayOptionSelect } from '~/queries/nodes/InsightViz/QuillDisplayOptionSelect'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import { smoothingOptions } from './smoothings'

export function SmoothingFilter(): JSX.Element | null {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { isTrends, interval, trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!isTrends || !interval) {
        return null
    }

    const { smoothingIntervals } = trendsFilter || {}
    const onSmoothingChange = (key: number): void => {
        updateInsightFilter({
            smoothingIntervals: key,
        })
    }

    if (todayRailNav && smoothingOptions[interval].length) {
        return (
            <QuillDisplayOptionSelect
                key={interval}
                value={smoothingIntervals || 1}
                options={smoothingOptions[interval]}
                onChange={onSmoothingChange}
                disabledReason={editingDisabledReason}
                fullWidth
                data-attr="smoothing-filter"
            />
        )
    }

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
            onChange={onSmoothingChange}
            data-attr="smoothing-filter"
            options={options}
            size="small"
            disabledReason={editingDisabledReason}
        />
    )
}
