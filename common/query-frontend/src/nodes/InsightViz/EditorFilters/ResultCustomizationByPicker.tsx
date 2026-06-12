import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { trendsDataLogic } from '@posthog/query-frontend/nodes/TrendsQuery/trendsDataLogic'
import { ResultCustomizationBy } from '@posthog/query-frontend/schema/schema-general'

import { insightLogic } from 'scenes/insights/insightLogic'

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
