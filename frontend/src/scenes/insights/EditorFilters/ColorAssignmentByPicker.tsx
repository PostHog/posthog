import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ColorAssignmentBy } from '~/queries/schema'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ColorAssignmentByPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { colorAssignmentBy } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            onChange={(value) => updateInsightFilter({ colorAssignmentBy: value as ColorAssignmentBy })}
            value={colorAssignmentBy || ColorAssignmentBy.Position}
            options={[
                { value: ColorAssignmentBy.Key, label: 'By key' },
                { value: ColorAssignmentBy.Position, label: 'By position' },
            ]}
            size="small"
            fullWidth
        />
    )
}
