import type { Meta, StoryObj } from '@storybook/react'
import { subDays, subMonths } from 'date-fns'
import * as React from 'react'

import { Button, Label, Switch, ToggleGroup, ToggleGroupItem } from '@posthog/quill-primitives'

import { DateRangeFilter, type DateRangeFilterPreset } from './date-range-filter'

const ANALYTICS_PRESETS: DateRangeFilterPreset<string>[] = [
    { id: 'today', label: 'Today', value: 'dStart', previewStart: (now) => now },
    { id: '7d', label: 'Last 7 days', value: '-7d', previewStart: (now) => subDays(now, 7) },
    { id: '30d', label: 'Last 30 days', value: '-30d', previewStart: (now) => subDays(now, 30) },
    { id: '90d', label: 'Last 90 days', value: '-90d', previewStart: (now) => subDays(now, 90) },
    { id: 'mStart', label: 'This month', value: 'mStart', previewStart: (now) => subMonths(now, 1) },
    { id: 'all', label: 'All time', value: 'all', previewStart: (now) => subMonths(now, 60) },
]

const meta: Meta<typeof DateRangeFilter> = {
    title: 'Blocks/DateRangeFilter',
    component: DateRangeFilter,
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof DateRangeFilter>

export const PresetList: Story = {
    render: () => (
        <div className="h-96">
            <DateRangeFilter
                label="Last 7 days"
                presets={ANALYTICS_PRESETS}
                selectedPresetId="7d"
                onPresetSelect={() => {}}
                onCustomApply={() => {}}
                defaultOpen
            />
        </div>
    ),
}

// Mirrors the insight date filter's footer: a compact "Days" row that expands day-of-week
// chips on demand, plus an exclude toggle — all host-supplied through the listFooter slot.
function DayOfWeekFooter(): React.ReactElement {
    const [days, setDays] = React.useState<string[]>([])
    const [expanded, setExpanded] = React.useState(false)
    const labels: Record<string, string> = { 1: 'M', 2: 'T', 3: 'W', 4: 'T', 5: 'F', 6: 'S', 7: 'S' }
    const summary =
        days.length === 0 || days.length === 7
            ? 'All days'
            : ['1', '2', '3', '4', '5'].every((d) => days.includes(d)) && days.length === 5
              ? 'Weekdays'
              : days.length === 2 && days.includes('6') && days.includes('7')
                ? 'Weekends'
                : `${days.length} days`
    return (
        <div className="flex flex-col p-1">
            <Button
                variant="default"
                left
                className="w-full justify-between"
                aria-expanded={expanded}
                onClick={() => setExpanded((prev) => !prev)}
            >
                <span>Days</span>
                <span className="text-muted-foreground">
                    {summary} {expanded ? '▴' : '▾'}
                </span>
            </Button>
            {expanded && (
                <div className="flex flex-col gap-1 px-1 py-1">
                    <ToggleGroup multiple size="sm" className="w-full max-w-60" value={days} onValueChange={setDays}>
                        {Object.keys(labels).map((day) => (
                            <ToggleGroupItem key={day} value={day} className="flex-1">
                                {labels[day]}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                    <div className="flex w-full max-w-60 items-center justify-center gap-2">
                        <Button variant="link" size="xs" onClick={() => setDays(['1', '2', '3', '4', '5'])}>
                            Weekdays
                        </Button>
                        <Button variant="link" size="xs" onClick={() => setDays(['6', '7'])}>
                            Weekends
                        </Button>
                        <Button variant="link" size="xs" onClick={() => setDays([])}>
                            All days
                        </Button>
                    </div>
                </div>
            )}
            <div className="flex items-center justify-between gap-2 px-2 py-1.5">
                <Label htmlFor="story-exclude-incomplete">Exclude incomplete period</Label>
                <Switch id="story-exclude-incomplete" size="sm" />
            </div>
        </div>
    )
}

export const WithListFooter: Story = {
    render: () => (
        <div className="h-120">
            <DateRangeFilter
                label="Last 7 days"
                presets={ANALYTICS_PRESETS}
                selectedPresetId="7d"
                onPresetSelect={() => {}}
                onCustomApply={() => {}}
                defaultOpen
                listFooter={<DayOfWeekFooter />}
            />
        </div>
    ),
}

export const CustomRangeActive: Story = {
    render: () => (
        <div className="h-120">
            <DateRangeFilter
                label="Jan 10 – Jan 20"
                presets={ANALYTICS_PRESETS}
                customActive
                customStart={new Date(2023, 0, 10)}
                customEnd={new Date(2023, 0, 20)}
                onPresetSelect={() => {}}
                onCustomApply={() => {}}
                defaultOpen
            />
        </div>
    ),
}
