import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'

import { retentionLogic } from './retentionLogic'

const ALL_KEY = '$all'

export function RetentionBreakdownFilterNext(): JSX.Element | null {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { breakdownValues, selectedBreakdownValue, breakdownDisplayNames } = useValues(retentionLogic(insightProps))
    const { setSelectedBreakdownValue } = useActions(retentionLogic(insightProps))

    if (!breakdownValues || breakdownValues.length === 0) {
        return null
    }

    const options = [
        { key: ALL_KEY, value: null as string | number | boolean | null, label: 'All breakdown values' },
        ...breakdownValues.map((value, index) => ({
            key: `value-${index}`,
            value: value as string | number | boolean | null,
            label:
                breakdownDisplayNames[String(value ?? '')] ||
                (value === null || value === '' ? '(empty)' : String(value)),
        })),
    ]
    const items = Object.fromEntries(options.map((option) => [option.key, option.label]))
    const selectedKey = options.find((option) => option.value === selectedBreakdownValue)?.key ?? ALL_KEY

    return (
        <Select
            value={selectedKey}
            items={items}
            onValueChange={(key: string | null) => {
                const option = options.find((o) => o.key === key)
                setSelectedBreakdownValue(option?.value ?? null)
            }}
            disabled={!!editingDisabledReason}
        >
            <SelectTrigger
                size="sm"
                data-quill
                data-attr="retention-breakdown-filter"
                title={editingDisabledReason ?? undefined}
            >
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.key} value={option.key}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
