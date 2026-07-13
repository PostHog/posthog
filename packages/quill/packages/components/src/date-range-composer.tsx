import {
    endOfMonth,
    endOfWeek,
    format,
    startOfDay,
    startOfMonth,
    startOfWeek,
    startOfYear,
    subDays,
    subHours,
    subMonths,
    subWeeks,
    subYears,
} from 'date-fns'
import { ChevronRight } from 'lucide-react'
import * as React from 'react'

import {
    Button,
    cn,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Separator,
    Switch,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill-primitives'

import { DateTimePicker, type DateTimeValue } from './date-time-picker'
import { CUSTOM_RANGE } from './date-time-ranges'
import { RelativeRangeInput, type RelativeRangeUnit, type RelativeRangeValue } from './relative-range-input'

/** CONCEPT — date filter redesign exploration ("the composer"), not a stable API.
 * Two aligned chip grids (shortened relative ranges, then calendar-anchored names) with the
 * `RelativeRangeInput` generalization between them, a custom-range calendar behind a footer
 * link, and exclusions collapsed behind a footer control that opens a portaled panel.
 * Chip vocabulary is overridable via props; hosts map selections to their own range model. */

export type DateRangeComposerSelection =
    | { kind: 'rolling'; count: number; unit: RelativeRangeUnit }
    | { kind: 'fixed'; name: string }
    | { kind: 'custom'; start: Date; end: Date }

type PresetSelection = Extract<DateRangeComposerSelection, { kind: 'rolling' } | { kind: 'fixed' }>

export interface DateRangeComposerChip {
    label: string
    selection: PresetSelection
}

export interface DateRangeComposerExclusions {
    days: string[]
    incomplete: boolean
}

// Rolling-range shortcuts, laid out as a 5-column grid: 1h 24h 7d 14d 30d / 90d 180d 1w 1m 1y.
// Every chip is a rolling window, so clicking one just sets the "In the last" input.
const DEFAULT_SHORT_CHIPS: DateRangeComposerChip[] = [
    { label: '1h', selection: { kind: 'rolling', count: 1, unit: 'hours' } },
    { label: '24h', selection: { kind: 'rolling', count: 24, unit: 'hours' } },
    { label: '7d', selection: { kind: 'rolling', count: 7, unit: 'days' } },
    { label: '14d', selection: { kind: 'rolling', count: 14, unit: 'days' } },
    { label: '30d', selection: { kind: 'rolling', count: 30, unit: 'days' } },
    { label: '90d', selection: { kind: 'rolling', count: 90, unit: 'days' } },
    { label: '180d', selection: { kind: 'rolling', count: 180, unit: 'days' } },
    { label: '1w', selection: { kind: 'rolling', count: 1, unit: 'weeks' } },
    { label: '1m', selection: { kind: 'rolling', count: 1, unit: 'months' } },
    { label: '1y', selection: { kind: 'rolling', count: 1, unit: 'years' } },
]
const DEFAULT_NAMED_CHIPS = ['Today', 'Yesterday', 'This week', 'This month', 'Year to date', 'All time']

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
        case 'This week':
            return { start: startOfWeek(now, { weekStartsOn: 1 }), end: now }
        case 'Last week': {
            const lastWeek = subWeeks(now, 1)
            return {
                start: startOfWeek(lastWeek, { weekStartsOn: 1 }),
                end: endOfWeek(lastWeek, { weekStartsOn: 1 }),
            }
        }
        case 'This month':
            return { start: startOfMonth(now), end: now }
        case 'Last month':
            return {
                start: startOfMonth(subMonths(now, 1)),
                end: endOfMonth(subMonths(now, 1)),
            }
        case 'Year to date':
            return { start: startOfYear(now), end: now }
        default:
            return { start: subYears(now, 10), end: now }
    }
}

const DAY_LABELS: Record<string, string> = {
    1: 'M',
    2: 'T',
    3: 'W',
    4: 'T',
    5: 'F',
    6: 'S',
    7: 'S',
}

function ExclusionsControl({
    exclusions,
    onChange,
    showDays,
    showIncomplete,
    panelProps,
}: {
    exclusions: DateRangeComposerExclusions
    onChange: (exclusions: DateRangeComposerExclusions) => void
    showDays: boolean
    showIncomplete: boolean
    panelProps?: React.HTMLAttributes<HTMLDivElement>
}): React.ReactElement {
    const summary = composerExclusionsSummary(exclusions)
    return (
        <Popover>
            <PopoverTrigger
                render={<Button variant="default" size="sm" left className="w-full" />}
                data-attr="date-composer-exclusions"
            >
                {summary || 'Exclude'}
                <ChevronRight className="ms-auto" />
            </PopoverTrigger>
            <PopoverContent side="right" align="end" {...panelProps} className="w-64 gap-0 p-0">
                {showIncomplete && (
                    <div className="flex items-center justify-between gap-2 px-3 py-2.5">
                        <Label htmlFor="composer-exclude-incomplete">Incomplete period</Label>
                        <Switch
                            id="composer-exclude-incomplete"
                            size="sm"
                            checked={exclusions.incomplete}
                            onCheckedChange={(incomplete) => onChange({ ...exclusions, incomplete })}
                        />
                    </div>
                )}
                {showIncomplete && showDays && <Separator />}
                {showDays && (
                    <div className="flex flex-col gap-2 px-3 py-2.5">
                        <ToggleGroup
                            multiple
                            size="sm"
                            spacing={1}
                            className="w-full"
                            value={exclusions.days}
                            onValueChange={(days) => onChange({ ...exclusions, days })}
                        >
                            {Object.keys(DAY_LABELS).map((day) => (
                                <ToggleGroupItem
                                    key={day}
                                    value={day}
                                    className="flex-1 data-[pressed]:border-primary data-[pressed]:bg-primary/10 data-[pressed]:text-primary"
                                    aria-label={`Exclude day ${day}`}
                                >
                                    {DAY_LABELS[day]}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                        <div className="flex items-center justify-center gap-3">
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
                                onClick={() =>
                                    onChange({
                                        ...exclusions,
                                        days: ['1', '2', '3', '4', '5'],
                                    })
                                }
                            >
                                Weekdays
                            </Button>
                            <Button
                                variant="link-muted"
                                size="xs"
                                onClick={() => onChange({ ...exclusions, days: [] })}
                            >
                                Clear
                            </Button>
                        </div>
                    </div>
                )}
            </PopoverContent>
        </Popover>
    )
}

const CHIP_CLASSES =
    'border-border bg-transparent aria-selected:border-primary aria-selected:bg-primary/10 aria-selected:font-semibold aria-selected:text-primary'

function chipSelected(chip: PresetSelection, selection: DateRangeComposerSelection): boolean {
    if (chip.kind === 'rolling') {
        return selection.kind === 'rolling' && selection.count === chip.count && selection.unit === chip.unit
    }
    return selection.kind === 'fixed' && selection.name === chip.name
}

function chipTitle(chip: PresetSelection, now: Date): string {
    if (chip.kind === 'rolling') {
        return `${format(rollingStart(chip.count, chip.unit, now), 'MMM d, yyyy')} – now`
    }
    const { start, end } = fixedRange(chip.name, now)
    return `${format(start, 'MMM d, yyyy')} – ${format(end, 'MMM d, yyyy')}`
}

export interface DateRangeComposerProps {
    selection: DateRangeComposerSelection
    onSelect: (selection: DateRangeComposerSelection) => void
    exclusions: DateRangeComposerExclusions
    onExclusionsChange: (exclusions: DateRangeComposerExclusions) => void
    shortChips?: DateRangeComposerChip[]
    namedChips?: string[]
    /** Renders an "Exact time range" switch in the footer when the handler is set (host semantics). */
    exactTime?: boolean
    onExactTimeChange?: (checked: boolean) => void
    /** Hide sections of the exclusions panel; the Exclude row disappears when both are off. */
    showExcludedDays?: boolean
    showIncompletePeriod?: boolean
    /** Extra props for the portaled surfaces (exclusions flyout, unit dropdown) — e.g. skin opt-in data attributes. */
    portalProps?: React.HTMLAttributes<HTMLDivElement>
}

export function DateRangeComposer({
    selection,
    onSelect,
    exclusions,
    onExclusionsChange,
    shortChips = DEFAULT_SHORT_CHIPS,
    namedChips = DEFAULT_NAMED_CHIPS,
    exactTime,
    onExactTimeChange,
    showExcludedDays = true,
    showIncompletePeriod = true,
    portalProps,
}: DateRangeComposerProps): React.ReactElement {
    const [calendarOpen, setCalendarOpen] = React.useState(false)
    const [includeTime, setIncludeTime] = React.useState(false)
    const rolling: RelativeRangeValue =
        selection.kind === 'rolling' ? { count: selection.count, unit: selection.unit } : { count: 7, unit: 'days' }
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
        <div
            className={cn(
                'overflow-hidden rounded-lg bg-card text-foreground shadow-md ring-1 ring-foreground/10',
                calendarOpen ? 'w-max' : 'w-80'
            )}
            data-attr="date-range-composer"
        >
            {calendarOpen ? (
                // The calendar replaces the whole surface (like the in-app filter's view swap);
                // Cancel returns to the preset view.
                <div className="flex flex-col">
                    <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5">
                        <Label htmlFor="composer-include-time">Include time</Label>
                        <Switch
                            id="composer-include-time"
                            size="sm"
                            checked={includeTime}
                            onCheckedChange={setIncludeTime}
                        />
                    </div>
                    <DateTimePicker
                        key={includeTime ? 'time' : 'day'}
                        showHeader={false}
                        showTime={includeTime}
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
            ) : (
                <div className="flex flex-col">
                    <div className="grid grid-cols-5 gap-1 px-3 pt-3 pb-1.5">
                        {shortChips.map(({ label, selection: chip }) => (
                            <Button
                                key={label}
                                variant="outline"
                                size="sm"
                                className={CHIP_CLASSES}
                                aria-selected={chipSelected(chip, selection)}
                                title={chipTitle(chip, now)}
                                onClick={() => onSelect(chip)}
                                data-attr={`date-composer-short-${label.toLowerCase()}`}
                            >
                                {label}
                            </Button>
                        ))}
                    </div>
                    <div className="flex items-center gap-2 px-3 py-1.5">
                        <Text size="sm" className="whitespace-nowrap" render={<span />}>
                            In the last
                        </Text>
                        <RelativeRangeInput
                            value={rolling}
                            onChange={({ count, unit }) => onSelect({ kind: 'rolling', count, unit })}
                            selectContentProps={portalProps}
                        />
                    </div>
                    <div className="grid grid-cols-3 gap-1 px-3 pt-1.5 pb-3">
                        {namedChips.map((name) => (
                            <Button
                                key={name}
                                variant="outline"
                                size="sm"
                                className={CHIP_CLASSES}
                                aria-selected={selection.kind === 'fixed' && selection.name === name}
                                title={chipTitle({ kind: 'fixed', name }, now)}
                                onClick={() => onSelect({ kind: 'fixed', name })}
                                data-attr={`date-composer-fixed-${name.toLowerCase().replace(/\s+/g, '-')}`}
                            >
                                {name}
                            </Button>
                        ))}
                    </div>
                    <div className="mt-auto flex flex-col gap-px border-t border-border p-1">
                        <Button
                            variant="default"
                            size="sm"
                            left
                            className="w-full"
                            aria-expanded={calendarOpen}
                            onClick={() => setCalendarOpen(true)}
                            data-attr="date-composer-custom-range"
                        >
                            Custom range…
                        </Button>
                        {onExactTimeChange && (
                            <div className="flex h-8 items-center justify-between gap-2 px-2">
                                <Label htmlFor="composer-exact-time">Exact time range</Label>
                                <Switch
                                    id="composer-exact-time"
                                    size="sm"
                                    checked={exactTime ?? false}
                                    onCheckedChange={onExactTimeChange}
                                />
                            </div>
                        )}
                        {(showExcludedDays || showIncompletePeriod) && (
                            <ExclusionsControl
                                exclusions={exclusions}
                                onChange={onExclusionsChange}
                                showDays={showExcludedDays}
                                showIncomplete={showIncompletePeriod}
                                panelProps={portalProps}
                            />
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
