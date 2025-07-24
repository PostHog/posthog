import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ResultCustomizationBy } from '~/queries/schema/schema-general'

import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

export function ResultCustomizationByPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { resultCustomizationBy } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            onChange={(value) => updateInsightFilter({ resultCustomizationBy: value as ResultCustomizationBy })}
            value={resultCustomizationBy}
            options={[
                { value: ResultCustomizationBy.Value, label: 'By name' },
                { value: ResultCustomizationBy.Position, label: 'By rank' },
            ]}
            size="small"
            fullWidth
        />
    )
}
