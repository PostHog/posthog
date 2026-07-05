import { useActions, useValues } from 'kea'

import { IconPin } from '@posthog/icons'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

export function IntervalFilterNext(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { interval, enabledIntervals, isIntervalManuallySet } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource, setIsIntervalManuallySet } = useActions(insightVizDataLogic(insightProps))

    const options = Object.entries(enabledIntervals)
        .filter(([, option]) => !option.hidden)
        .map(([value, { label, disabledReason }]) => ({
            value: value as IntervalType,
            label,
            disabledReason,
        }))
    // Hidden intervals (e.g. quarter) can still be the current value, so the trigger label needs them
    const items = Object.fromEntries(Object.entries(enabledIntervals).map(([value, { label }]) => [value, label]))

    return (
        <span className="flex items-center gap-2">
            <span className="@max-[780px]:hidden">
                <span className="hidden md:inline">grouped </span>by
            </span>
            {isIntervalManuallySet ? (
                <Button
                    variant="outline"
                    size="sm"
                    data-quill
                    data-attr="interval-filter-unpin"
                    onClick={() => setIsIntervalManuallySet(false)}
                    disabled={!!editingDisabledReason}
                    title={editingDisabledReason ?? 'Unpin interval'}
                >
                    <IconPin color="var(--content-warning)" />
                    {interval || 'day'}
                </Button>
            ) : (
                <Select
                    value={interval || 'day'}
                    items={items}
                    onValueChange={(value: string | null) => {
                        if (value) {
                            updateQuerySource({ interval: value as IntervalType } as Partial<InsightQueryNode>)
                        }
                    }}
                    disabled={!!editingDisabledReason}
                >
                    <SelectTrigger
                        size="sm"
                        data-quill
                        data-attr="interval-filter"
                        title={editingDisabledReason ?? undefined}
                    >
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {options.map((option) => (
                            <SelectItem
                                key={option.value}
                                value={option.value}
                                disabled={!!option.disabledReason}
                                title={option.disabledReason ?? undefined}
                            >
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            )}
        </span>
    )
}
