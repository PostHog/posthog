import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { retentionLogic } from './retentionLogic'
import { retentionTableLogic } from './retentionTableLogic'

export function RetentionBreakdownFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { breakdownValues, selectedBreakdownValue } = useValues(retentionTableLogic(insightProps))
    const { setSelectedBreakdownValue } = useActions(retentionLogic(insightProps))

    if (!breakdownValues || breakdownValues.length === 0) {
        return null
    }

    const options = breakdownValues
        .filter((value) => !!value)
        .map((value) => ({
            value: value as string | number | boolean,
            label: value === null ? '(empty)' : String(value),
        }))

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
