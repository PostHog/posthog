import { IconChevronRight } from '@posthog/icons'
import {
    Button,
    cn,
    CUSTOM_RANGE,
    Text,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
    type DateTimeValue,
} from '@posthog/quill'

import { dayjs, type Dayjs } from 'lib/dayjs'
import { startOfWeek } from 'lib/utils/dateFilters'

import { RelativeRangeInput, type RelativeRangeUnit, type RelativeRangeValue } from './RelativeRangeInput'

/** The badge presets panel for the quill DateTimePicker, composed app-side while the design is
 * experimental. The panel never interprets selections — hosts map them to their own range model. */

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
const DEFAULT_NAMED_CHIPS = ['Today', 'Yesterday', 'This week', 'This month', 'This year', 'All time']

export function dateRangeSelectionLabel(selection: DateRangeSelection): string {
    if (selection.kind === 'rolling') {
        const unit = selection.count === 1 ? selection.unit.slice(0, -1) : selection.unit
        return `Last ${selection.count} ${unit}`
    }
    if (selection.kind === 'fixed') {
        return selection.name
    }
    return `${dayjs(selection.start).format('MMM D')} – ${dayjs(selection.end).format('MMM D')}`
}

function rollingStart(count: number, unit: RelativeRangeUnit, now: Dayjs): Dayjs {
    return now.subtract(count, unit)
}

// "All time" has no real start — seed the calendar with a span long enough to look unbounded.
const ALL_TIME_SEED_YEARS = 10

function fixedRange(name: string, now: Dayjs, weekStartsOn: 0 | 1): { start: Dayjs; end: Dayjs } {
    switch (name) {
        case 'Today':
            return { start: now.startOf('day'), end: now }
        case 'Yesterday':
            return { start: now.subtract(1, 'day').startOf('day'), end: now.subtract(1, 'day').endOf('day') }
        case 'This week':
            return { start: startOfWeek(now, weekStartsOn), end: now }
        case 'Last week': {
            const start = startOfWeek(now.subtract(1, 'week'), weekStartsOn)
            return { start, end: start.add(6, 'days').endOf('day') }
        }
        case 'This month':
            return { start: now.startOf('month'), end: now }
        case 'Last month':
            return { start: now.subtract(1, 'month').startOf('month'), end: now.subtract(1, 'month').endOf('month') }
        case 'This year':
            return { start: now.startOf('year'), end: now }
        default:
            return { start: now.subtract(ALL_TIME_SEED_YEARS, 'years'), end: now }
    }
}

export function valueForSelection(selection: DateRangeSelection, now: Dayjs, weekStartsOn: 0 | 1): DateTimeValue {
    if (selection.kind === 'custom') {
        return { start: selection.start, end: selection.end, range: CUSTOM_RANGE }
    }
    if (selection.kind === 'rolling') {
        return {
            start: rollingStart(selection.count, selection.unit, now).toDate(),
            end: now.toDate(),
            range: CUSTOM_RANGE,
        }
    }
    const { start, end } = fixedRange(selection.name, now, weekStartsOn)
    return { start: start.toDate(), end: end.toDate(), range: CUSTOM_RANGE }
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
    'h-6 px-1.5 text-[0.75rem] border-border bg-transparent aria-selected:border-primary aria-selected:bg-primary/10 aria-selected:font-semibold aria-selected:text-primary'

function chipSelected(chip: PresetSelection, selection: DateRangeSelection): boolean {
    if (chip.kind === 'rolling') {
        return selection.kind === 'rolling' && selection.count === chip.count && selection.unit === chip.unit
    }
    return selection.kind === 'fixed' && selection.name === chip.name
}

function chipTitle(chip: PresetSelection, now: Dayjs, weekStartsOn: 0 | 1): string {
    if (chip.kind === 'rolling') {
        return `${rollingStart(chip.count, chip.unit, now).format('MMM D, YYYY')} – now`
    }
    const { start, end } = fixedRange(chip.name, now, weekStartsOn)
    return `${start.format('MMM D, YYYY')} – ${end.format('MMM D, YYYY')}`
}

export interface DateRangePresetsPanelProps {
    selection: DateRangeSelection
    onSelectionChange?: (selection: DateRangeSelection) => void
    shortChips?: DateRangeChip[]
    namedChips?: string[]
    /** Frozen "now" shared with the calendar seed so chip titles and the seed agree. */
    now: Dayjs
    weekStartsOn: 0 | 1
    calendarOpen: boolean
    onCalendarOpenChange?: (open: boolean) => void
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
}: DateRangePresetsPanelProps): JSX.Element {
    const rolling: RelativeRangeValue =
        selection.kind === 'rolling' ? { count: selection.count, unit: selection.unit } : { count: 7, unit: 'days' }

    return (
        <TooltipProvider delay={1000} timeout={0}>
            <div className="flex h-full w-56 shrink-0 flex-col">
                <div className="grid grid-cols-3 gap-1 px-2 pt-2 pb-1.5">
                    {shortChips.map(({ label, selection: chip }) => (
                        <Tooltip key={label}>
                            <TooltipTrigger
                                render={
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className={CHIP_CLASSES}
                                        aria-selected={chipSelected(chip, selection)}
                                        onClick={() => onSelectionChange?.(chip)}
                                        data-attr={`date-presets-chip-${label.toLowerCase()}`}
                                    />
                                }
                            >
                                {label}
                            </TooltipTrigger>
                            <TooltipContent {...portalProps}>{chipTitle(chip, now, weekStartsOn)}</TooltipContent>
                        </Tooltip>
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
                        <Tooltip key={name}>
                            <TooltipTrigger
                                render={
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className={CHIP_CLASSES}
                                        aria-selected={selection.kind === 'fixed' && selection.name === name}
                                        onClick={() => onSelectionChange?.({ kind: 'fixed', name })}
                                        data-attr={`date-presets-chip-${name.toLowerCase().replace(/\s+/g, '-')}`}
                                    />
                                }
                            >
                                {name}
                            </TooltipTrigger>
                            <TooltipContent {...portalProps}>
                                {chipTitle({ kind: 'fixed', name }, now, weekStartsOn)}
                            </TooltipContent>
                        </Tooltip>
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
                                <IconChevronRight
                                    className={cn('ms-auto transition-transform', calendarOpen && 'rotate-90')}
                                />
                            </Button>
                        )}
                        {footer}
                    </div>
                )}
            </div>
        </TooltipProvider>
    )
}
