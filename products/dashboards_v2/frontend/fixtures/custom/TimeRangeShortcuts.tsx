import { useContext } from 'react'

import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { FilterControlsContext } from '../../filters/filtersContext'

const SHORTCUTS = [
    { from: 'now-24h', label: 'Today' },
    { from: 'now-7d', label: 'This week' },
    { from: 'now-30d', label: 'This month' },
]

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product drives its filters from its own custom content.
export function TimeRangeShortcuts(): JSX.Element | null {
    const { timeRange } = useContext(FilterControlsContext)
    if (!timeRange) {
        return null
    }
    const picked = SHORTCUTS.find((shortcut) => shortcut.from === timeRange.value?.from)?.from
    return (
        <div className="flex h-full items-center justify-between gap-4">
            <div className="font-semibold">Period</div>
            <ToggleGroup
                variant="outline"
                size="sm"
                value={picked ? [picked] : []}
                onValueChange={(values: string[]) =>
                    timeRange.onChange(values[0] ? { from: values[0], to: 'now' } : undefined)
                }
            >
                {SHORTCUTS.map(({ from, label }) => (
                    <ToggleGroupItem key={from} value={from} data-attr="dashboard-v2-example-time-shortcut">
                        {label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
