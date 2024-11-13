import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ColorAssignmentByPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { colorAssignmentBy } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            onChange={(value) => updateInsightFilter({ colorAssignmentBy: value as 'key' | 'position' })}
            value={colorAssignmentBy || 'key'}
            options={[
                { value: 'key', label: 'By key' },
                { value: 'position', label: 'By position' },
            ]}
            size="small"
            fullWidth
        />
    )
}
