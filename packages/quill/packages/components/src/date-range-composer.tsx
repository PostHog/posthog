import {
    endOfMonth,
    format,
    startOfDay,
    startOfMonth,
    startOfYear,
    subDays,
    subHours,
    subMonths,
    subWeeks,
    subYears,
} from 'date-fns'
import * as React from 'react'

import { Button, Separator, Switch, Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill-primitives'

import { DateTimePicker, type DateTimeValue } from './date-time-picker'
import { CUSTOM_RANGE } from './date-time-ranges'
import { RelativeRangeInput, type RelativeRangeUnit, type RelativeRangeValue } from './relative-range-input'

/** CONCEPT — date filter redesign exploration ("the composer"), not a stable API.
 * Rolling shortcuts and fixed presets as chips, `RelativeRangeInput` as the generalization,
 * with a custom-range calendar and an exclusions drawer behind footer links.
 * Lives here (rather than in the stories) so the app storybook can render it next to the
 * Lemon-skin twin. Chip vocabulary is overridable via props; hosts map selections to their
 * own range model. */

export type DateRangeComposerSelection =
    | { kind: 'rolling'; count: number; unit: RelativeRangeUnit }
    | { kind: 'fixed'; name: string }
    | { kind: 'custom'; start: Date; end: Date }

export interface DateRangeComposerExclusions {
    days: string[]
    incomplete: boolean
}

// Rolling shortcuts sorted by duration, counts ranked by production click share.
const DEFAULT_ROLLING_CHIPS: { count: number; unit: RelativeRangeUnit }[] = [
    { count: 1, unit: 'hours' },
    { count: 24, unit: 'hours' },
    { count: 7, unit: 'days' },
    { count: 14, unit: 'days' },
    { count: 30, unit: 'days' },
    { count: 90, unit: 'days' },
    { count: 180, unit: 'days' },
    { count: 12, unit: 'months' },
]
const DEFAULT_FIXED_CHIPS = ['Today', 'Yesterday', 'This month', 'Last month', 'Year to date', 'All time']

export function composerSelectionLabel(selection: DateRangeComposerSelection): string {
    if (selection.kind === 'rolling') {
        const unit = selection.count === 1 ? selection.unit.slice(0, -1) : selection.unit
        return `Last ${selection.count} ${unit}`
    }
    if (selection.kind === 'fixed') {
        return selection.name
    }
    return `${format(selection.start, 'MMM d')} – ${format(selection.end, 'MMM d')}`
}

export function composerExclusionsSummary({ days, incomplete }: DateRangeComposerExclusions): string {
    const parts: string[] = []
    if (days.length > 0) {
        const sorted = [...days].sort().join(',')
        parts.push(sorted === '6,7' ? 'weekends' : sorted === '1,2,3,4,5' ? 'weekdays' : `${days.length} days`)
    }
    if (incomplete) {
        parts.push('incomplete')
    }
    return parts.length > 0 ? `Excluding ${parts.join(', ')}` : ''
}

function rollingStart(count: number, unit: RelativeRangeUnit, now: Date): Date {
    switch (unit) {
        case 'minutes':
            return new Date(now.getTime() - count * 60_000)
        case 'hours':
            return subHours(now, count)
        case 'days':
            return subDays(now, count)
        case 'weeks':
            return subWeeks(now, count)
        case 'months':
            return subMonths(now, count)
        case 'years':
            return subYears(now, count)
    }
}

function fixedRange(name: string, now: Date): { start: Date; end: Date } {
    switch (name) {
        case 'Today':
            return { start: startOfDay(now), end: now }
        case 'Yesterday':
            return { start: startOfDay(subDays(now, 1)), end: startOfDay(now) }
        case 'This month':
            return { start: startOfMonth(now), end: now }
        case 'Last month':
            return { start: startOfMonth(subMonths(now, 1)), end: endOfMonth(subMonths(now, 1)) }
        case 'Year to date':
            return { start: startOfYear(now), end: now }
        default:
            return { start: subYears(now, 10), end: now }
    }
}

function ExclusionsDrawer({
    exclusions,
    onChange,
}: {
    exclusions: DateRangeComposerExclusions
    onChange: (exclusions: DateRangeComposerExclusions) => void
}): React.ReactElement {
    const labels: Record<string, string> = {
        1: 'M',
        2: 'T',
        3: 'W',
        4: 'T',
        5: 'F',
        6: 'S',
        7: 'S',
    }
    return (
        <div className="flex flex-col gap-2 border-t border-border bg-foreground/[0.03] px-3 py-2.5">
            <div className="flex items-center justify-between gap-2">
                <Text size="xs" className="whitespace-nowrap" render={<label htmlFor="composer-exclude-incomplete" />}>
                    Skip incomplete period
                </Text>
                <Switch
                    id="composer-exclude-incomplete"
                    size="sm"
                    checked={exclusions.incomplete}
                    onCheckedChange={(incomplete) => onChange({ ...exclusions, incomplete })}
                />
            </div>
            <div className="flex items-center justify-between gap-2">
                <Text size="xs" className="whitespace-nowrap" render={<span />}>
                    Exclude days
                </Text>
                <div className="flex items-center gap-2">
                    <Button
                        variant="link-muted"
                        size="xs"
                        onClick={() => onChange({ ...exclusions, days: ['6', '7'] })}
                    >
                        Weekends
                    </Button>
                    <Button
                        variant="link-muted"
                        size="xs"
                        onClick={() => onChange({ ...exclusions, days: ['1', '2', '3', '4', '5'] })}
                    >
                        Weekdays
                    </Button>
                    <Button variant="link-muted" size="xs" onClick={() => onChange({ ...exclusions, days: [] })}>
                        Clear
                    </Button>
                </div>
            </div>
            <ToggleGroup
                multiple
                size="sm"
                spacing={1}
                className="w-full"
                value={exclusions.days}
                onValueChange={(days) => onChange({ ...exclusions, days })}
            >
                {Object.keys(labels).map((day) => (
                    <ToggleGroupItem
                        key={day}
                        value={day}
                        className="flex-1 data-[pressed]:border-primary data-[pressed]:bg-primary/10 data-[pressed]:text-primary"
                        aria-label={`Exclude day ${day}`}
                    >
                        {labels[day]}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}

const CHIP_CLASSES =
    'border-border bg-transparent aria-selected:border-primary aria-selected:bg-primary/10 aria-selected:font-semibold aria-selected:text-primary'

export interface DateRangeComposerProps {
    selection: DateRangeComposerSelection
    onSelect: (selection: DateRangeComposerSelection) => void
    exclusions: DateRangeComposerExclusions
    onExclusionsChange: (exclusions: DateRangeComposerExclusions) => void
    rollingChips?: { count: number; unit: RelativeRangeUnit }[]
    fixedChips?: string[]
}

export function DateRangeComposer({
    selection,
    onSelect,
    exclusions,
    onExclusionsChange,
    rollingChips = DEFAULT_ROLLING_CHIPS,
    fixedChips = DEFAULT_FIXED_CHIPS,
}: DateRangeComposerProps): React.ReactElement {
    const [calendarOpen, setCalendarOpen] = React.useState(false)
    const [excludeOpen, setExcludeOpen] = React.useState(false)
    const rolling: RelativeRangeValue =
        selection.kind === 'rolling' ? { count: selection.count, unit: selection.unit } : { count: 7, unit: 'days' }
    const summary = composerExclusionsSummary(exclusions)
    const now = new Date()

    const calendarValue: DateTimeValue =
        selection.kind === 'custom'
            ? {
                  start: selection.start,
                  end: selection.end,
                  range: CUSTOM_RANGE,
              }
            : selection.kind === 'rolling'
              ? {
                    start: rollingStart(selection.count, selection.unit, now),
                    end: now,
                    range: CUSTOM_RANGE,
                }
              : { ...fixedRange(selection.name, now), range: CUSTOM_RANGE }

    return (
        <div className="w-72 overflow-hidden rounded-lg bg-card text-foreground shadow-md ring-1 ring-foreground/10">
            <div className="flex flex-col">
                <div className="flex flex-wrap gap-1 px-3 pt-3 pb-2">
                    {rollingChips.map(({ count, unit }) => (
                        <Button
                            key={`${count}-${unit}`}
                            variant="outline"
                            size="sm"
                            className={CHIP_CLASSES}
                            aria-selected={
                                selection.kind === 'rolling' && selection.count === count && selection.unit === unit
                            }
                            onClick={() => onSelect({ kind: 'rolling', count, unit })}
                            data-attr={`date-composer-rolling-${count}-${unit}`}
                        >
                            {count} {unit.slice(0, 1)}
                        </Button>
                    ))}
                </div>
                <Separator />
                <div className="flex items-center gap-2 px-3 py-2">
                    <Text size="sm" weight="semibold" render={<span />}>
                        Last
                    </Text>
                    <RelativeRangeInput
                        value={rolling}
                        onChange={({ count, unit }) => onSelect({ kind: 'rolling', count, unit })}
                    />
                </div>
                <Separator />
                <div className="flex flex-wrap gap-1 px-3 py-2">
                    {fixedChips.map((name) => (
                        <Button
                            key={name}
                            variant="outline"
                            size="sm"
                            className={CHIP_CLASSES}
                            aria-selected={selection.kind === 'fixed' && selection.name === name}
                            onClick={() => onSelect({ kind: 'fixed', name })}
                            data-attr={`date-composer-fixed-${name.toLowerCase().replace(/\s+/g, '-')}`}
                        >
                            {name}
                        </Button>
                    ))}
                </div>
                <div className="mt-auto flex items-center justify-between border-t border-border px-3 py-1.5">
                    <Button
                        variant="link"
                        size="xs"
                        aria-expanded={calendarOpen}
                        onClick={() => setCalendarOpen((prev) => !prev)}
                        data-attr="date-composer-custom-range"
                    >
                        Custom range…
                    </Button>
                    <Button
                        variant="link"
                        size="xs"
                        aria-expanded={excludeOpen}
                        onClick={() => setExcludeOpen((prev) => !prev)}
                        data-attr="date-composer-exclusions"
                    >
                        {summary || '+ Exclude'}
                    </Button>
                </div>
                {excludeOpen && <ExclusionsDrawer exclusions={exclusions} onChange={onExclusionsChange} />}
                {calendarOpen && (
                    <div className="border-t border-border">
                        <DateTimePicker
                            compact
                            showHeader={false}
                            showTime={false}
                            ranges={[]}
                            value={calendarValue}
                            onApply={({ start, end }) => {
                                onSelect({ kind: 'custom', start, end })
                                setCalendarOpen(false)
                            }}
                            onCancel={() => setCalendarOpen(false)}
                            className="w-full rounded-none shadow-none ring-0"
                        />
                    </div>
                )}
            </div>
        </div>
    )
}
