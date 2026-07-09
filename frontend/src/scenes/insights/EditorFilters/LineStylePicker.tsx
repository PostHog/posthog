import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import type { TrendsFilter } from '~/queries/schema/schema-general'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function LineStylePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    // chartStyle exists on every filter kind this picker renders for (trends, stickiness,
    // retention, funnels) — TrendsFilter stands in for the union member carrying it.
    const chartStyle = (insightFilter as TrendsFilter | undefined)?.chartStyle

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            onChange={(value) =>
                updateInsightFilter({
                    chartStyle: { ...chartStyle, curve: value as 'smooth' | 'linear' },
                })
            }
            // Unset curve falls through to the app default, which is smooth under the style-refresh
            // flag (the only context this picker renders in).
            value={chartStyle?.curve || 'smooth'}
            options={[
                { value: 'smooth', label: 'Smooth' },
                { value: 'linear', label: 'Straight' },
            ]}
            size="small"
            fullWidth
        />
    )
}
