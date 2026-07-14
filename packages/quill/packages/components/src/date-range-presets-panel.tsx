import {
    endOfDay,
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

import { Button, Text, cn } from '@posthog/quill-primitives'

import type { DateTimeValue } from './date-time-picker'
import { CUSTOM_RANGE } from './date-time-ranges'
import { RelativeRangeInput, type RelativeRangeUnit, type RelativeRangeValue } from './relative-range-input'

/** The picker's preset vocabulary. The picker never interprets what a selection means beyond
 *  previewing it on the calendar — hosts map selections to their own range model. */
export type DateRangeSelection =
    | { kind: 'rolling'; count: number; unit: RelativeRangeUnit }
    | { kind: 'fixed'; name: string }
    | { kind: 'custom'; start: Date; end: Date; includesTime?: boolean }

type PresetSelection = Extract<DateRangeSelection, { kind: 'rolling' } | { kind: 'fixed' }>

export interface DateRangeChip {
    label: string
    selection: PresetSelection
}

/** Portaled surfaces escape wrapper-scoped selectors, so skin opt-in rides in as data attributes. */
export type DataAttributeProps = React.HTMLAttributes<HTMLDivElement> & Record<`data-${string}`, string>

const DEFAULT_SHORT_CHIPS: DateRangeChip[] = [
    { label: '1h', selection: { kind: 'rolling', count: 1, unit: 'hours' } },
    { label: '24h', selection: { kind: 'rolling', count: 24, unit: 'hours' } },
    { label: '7d', selection: { kind: 'rolling', count: 7, unit: 'days' } },
    { label: '14d', selection: { kind: 'rolling', count: 14, unit: 'days' } },
    { label: '30d', selection: { kind: 'rolling', count: 30, unit: 'days' } },
    { label: '90d', selection: { kind: 'rolling', count: 90, unit: 'days' } },
    { label: '1w', selection: { kind: 'rolling', count: 1, unit: 'weeks' } },
    { label: '1m', selection: { kind: 'rolling', count: 1, unit: 'months' } },
    { label: '1y', selection: { kind: 'rolling', count: 1, unit: 'years' } },
]
const DEFAULT_NAMED_CHIPS = ['Today', 'Yesterday', 'This week', 'This month', 'Year to date', 'All time']

export function dateRangeSelectionLabel(selection: DateRangeSelection): string {
    if (selection.kind === 'rolling') {
        const unit = selection.count === 1 ? selection.unit.slice(0, -1) : selection.unit
        return `Last ${selection.count} ${unit}`
    }
    if (selection.kind === 'fixed') {
        return selection.name
    }
    return `${format(selection.start, 'MMM d')} – ${format(selection.end, 'MMM d')}`
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

function fixedRange(name: string, now: Date, weekStartsOn: 0 | 1): { start: Date; end: Date } {
    switch (name) {
        case 'Today':
            return { start: startOfDay(now), end: now }
        case 'Yesterday':
            return { start: startOfDay(subDays(now, 1)), end: endOfDay(subDays(now, 1)) }
        case 'This week':
            return { start: startOfWeek(now, { weekStartsOn }), end: now }
        case 'Last week': {
            const lastWeek = subWeeks(now, 1)
            return { start: startOfWeek(lastWeek, { weekStartsOn }), end: endOfWeek(lastWeek, { weekStartsOn }) }
        }
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

export function valueForSelection(selection: DateRangeSelection, now: Date, weekStartsOn: 0 | 1): DateTimeValue {
    if (selection.kind === 'custom') {
        return { start: selection.start, end: selection.end, range: CUSTOM_RANGE }
    }
    if (selection.kind === 'rolling') {
        return { start: rollingStart(selection.count, selection.unit, now), end: now, range: CUSTOM_RANGE }
    }
    return { ...fixedRange(selection.name, now, weekStartsOn), range: CUSTOM_RANGE }
}

export function selectionKeyOf(selection: DateRangeSelection): string {
    if (selection.kind === 'custom') {
        return `custom-${selection.start.getTime()}-${selection.end.getTime()}`
    }
    if (selection.kind === 'rolling') {
        return `rolling-${selection.count}-${selection.unit}`
    }
    return `fixed-${selection.name}`
}

const CHIP_CLASSES =
    'h-5 px-1 text-[0.6875rem] border-border bg-transparent aria-selected:border-primary aria-selected:bg-primary/10 aria-selected:font-semibold aria-selected:text-primary'

function chipSelected(chip: PresetSelection, selection: DateRangeSelection): boolean {
    if (chip.kind === 'rolling') {
        return selection.kind === 'rolling' && selection.count === chip.count && selection.unit === chip.unit
    }
    return selection.kind === 'fixed' && selection.name === chip.name
}

function chipTitle(chip: PresetSelection, now: Date, weekStartsOn: 0 | 1): string {
    if (chip.kind === 'rolling') {
        return `${format(rollingStart(chip.count, chip.unit, now), 'MMM d, yyyy')} – now`
    }
    const { start, end } = fixedRange(chip.name, now, weekStartsOn)
    return `${format(start, 'MMM d, yyyy')} – ${format(end, 'MMM d, yyyy')}`
}

export interface DateRangePresetsPanelProps {
    selection: DateRangeSelection
    onSelectionChange?: (selection: DateRangeSelection) => void
    shortChips?: DateRangeChip[]
    namedChips?: string[]
    /** Frozen "now" shared with the picker so chip titles and the derived seed agree. */
    now: Date
    weekStartsOn: 0 | 1
    calendarOpen: boolean
    /** When set, renders the "Custom range…" expander row; omit for an always-visible calendar. */
    onCalendarOpenChange?: (open: boolean) => void
    /** Extra host rows at the bottom of the panel. */
    footer?: React.ReactNode
    portalProps?: DataAttributeProps
}

export function DateRangePresetsPanel({
    selection,
    onSelectionChange,
    shortChips = DEFAULT_SHORT_CHIPS,
    namedChips = DEFAULT_NAMED_CHIPS,
    now,
    weekStartsOn,
    calendarOpen,
    onCalendarOpenChange,
    footer,
    portalProps,
}: DateRangePresetsPanelProps): React.ReactElement {
    const rolling: RelativeRangeValue =
        selection.kind === 'rolling' ? { count: selection.count, unit: selection.unit } : { count: 7, unit: 'days' }

    return (
        <div className="flex h-full w-56 flex-col">
            <div className="grid grid-cols-3 gap-1 px-2 pt-2 pb-1.5">
                {shortChips.map(({ label, selection: chip }) => (
                    <Button
                        key={label}
                        variant="outline"
                        size="sm"
                        className={CHIP_CLASSES}
                        aria-selected={chipSelected(chip, selection)}
                        title={chipTitle(chip, now, weekStartsOn)}
                        onClick={() => onSelectionChange?.(chip)}
                        data-attr={`date-presets-chip-${label.toLowerCase()}`}
                    >
                        {label}
                    </Button>
                ))}
            </div>
            <div className="flex flex-wrap items-center gap-1.5 px-2 py-1.5">
                <Text size="sm" className="whitespace-nowrap" render={<span />}>
                    Last
                </Text>
                <RelativeRangeInput
                    className="gap-1.5 [&_[data-slot=input-group]]:w-[5.5rem] [&_[data-slot=input-group]_input]:px-0"
                    value={rolling}
                    onChange={({ count, unit }) => onSelectionChange?.({ kind: 'rolling', count, unit })}
                    selectContentProps={portalProps}
                />
            </div>
            <div className="grid grid-cols-2 gap-1 px-2 pt-1.5 pb-2">
                {namedChips.map((name) => (
                    <Button
                        key={name}
                        variant="outline"
                        size="sm"
                        className={CHIP_CLASSES}
                        aria-selected={selection.kind === 'fixed' && selection.name === name}
                        title={chipTitle({ kind: 'fixed', name }, now, weekStartsOn)}
                        onClick={() => onSelectionChange?.({ kind: 'fixed', name })}
                        data-attr={`date-presets-chip-${name.toLowerCase().replace(/\s+/g, '-')}`}
                    >
                        {name}
                    </Button>
                ))}
            </div>
            {(onCalendarOpenChange || footer) && (
                <div className="mt-auto flex flex-col gap-px border-t border-border p-1">
                    {onCalendarOpenChange && (
                        <Button
                            variant="default"
                            size="sm"
                            left
                            className="w-full"
                            aria-expanded={calendarOpen}
                            onClick={() => onCalendarOpenChange(!calendarOpen)}
                            data-attr="date-presets-custom-range"
                        >
                            Custom range…
                            <ChevronRight className={cn('ms-auto transition-transform', calendarOpen && 'rotate-90')} />
                        </Button>
                    )}
                    {footer}
                </div>
            )}
        </div>
    )
}
