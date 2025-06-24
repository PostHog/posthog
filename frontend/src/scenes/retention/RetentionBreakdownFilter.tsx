import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { retentionLogic } from './retentionLogic'

export function RetentionBreakdownFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { breakdownValues, selectedBreakdownValue } = useValues(retentionLogic(insightProps))
    const { setSelectedBreakdownValue } = useActions(retentionLogic(insightProps))

    if (!breakdownValues || breakdownValues.length === 0) {
        return null
    }

    const options = [
        { value: null, label: 'All breakdown values' },
        ...breakdownValues.map((value) => ({
            value: value as string | number | boolean,
            label: value === null || value === '' ? '(empty)' : value,
        })),
    ]

    return (
        <LemonSelect
            value={selectedBreakdownValue}
            onChange={(value) => setSelectedBreakdownValue(value)}
            options={options as LemonSelectOption<string | number | boolean | null>[]}
            placeholder="Select breakdown value"
            size="small"
            data-attr="retention-breakdown-filter"
        />
    )
}
