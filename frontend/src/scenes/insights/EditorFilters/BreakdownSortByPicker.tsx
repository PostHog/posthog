import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { BreakdownSortBy } from '~/queries/schema/schema-general'

export function BreakdownSortByPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { breakdownSortBy } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            onChange={(value) => updateInsightFilter({ breakdownSortBy: value as BreakdownSortBy })}
            value={breakdownSortBy}
            options={[
                { value: BreakdownSortBy.AggregateValue, label: 'Aggregate value' },
                { value: BreakdownSortBy.Name, label: 'Name (A–Z)' },
            ]}
            size="small"
            fullWidth
        />
    )
}
