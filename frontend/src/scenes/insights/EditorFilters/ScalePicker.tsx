import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ScalePicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            onChange={(value) => updateInsightFilter({ yAxisScaleType: value as 'linear' | 'log10' })}
            value={yAxisScaleType || 'linear'}
            options={[
                { value: 'linear', label: 'Linear' },
                { value: 'log10', label: 'Logarithmic' },
            ]}
            size="small"
            fullWidth
        />
    )
}
