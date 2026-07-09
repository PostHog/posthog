import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function LineStylePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            onChange={(value) =>
                updateInsightFilter({
                    chartStyle: { ...trendsFilter?.chartStyle, curve: value as 'smooth' | 'linear' },
                })
            }
            // Unset curve falls through to the app default, which is smooth under the style-refresh
            // flag (the only context this picker renders in).
            value={trendsFilter?.chartStyle?.curve || 'smooth'}
            options={[
                { value: 'smooth', label: 'Smooth' },
                { value: 'linear', label: 'Straight' },
            ]}
            size="small"
            fullWidth
        />
    )
}
