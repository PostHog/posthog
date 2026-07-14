import {
    endOfDay,
    endOfMonth,
    endOfWeek,
    format,
    getMonth,
    getYear,
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
import { ArrowRight, ChevronRight, SettingsIcon } from 'lucide-react'
import * as React from 'react'

import { Badge, Button, ScrollArea, Separator, Switch, Text, cn } from '@posthog/quill-primitives'

import { Calendar } from './calendar-grid'
import { CUSTOM_RANGE, type DateTimeRange, quickRanges } from './date-time-ranges'
import { RelativeRangeInput, type RelativeRangeUnit, type RelativeRangeValue } from './relative-range-input'
import { SegmentedDateInput, type DateFormatOrder } from './segmented-date-input'
import { Day } from './use-calendar'

export type { DateFormatOrder } from './segmented-date-input'

const DATE_TIME_FORMATS: Record<DateFormatOrder, string> = {
    MDY: 'MM/dd/yy HH:mm:ss',
    DMY: 'dd/MM/yy HH:mm:ss',
    YMD: 'yy-MM-dd HH:mm:ss',
}

const DATE_FORMATS: Record<DateFormatOrder, string> = {
    MDY: 'MM/dd/yy',
    DMY: 'dd/MM/yy',
    YMD: 'yy-MM-dd',
}

// Tailwind `lg` breakpoint — matches the `lg:` classes that switch this picker
// between a single calendar and the side-by-side dual-calendar layout.
const LG_QUERY = '(min-width: 64rem)'

function useMediaQuery(query: string): boolean {
    const [matches, setMatches] = React.useState(false)
    React.useEffect(() => {
        const mql = window.matchMedia(query)
        const update = (): void => setMatches(mql.matches)
        update()
        mql.addEventListener('change', update)
        return () => mql.removeEventListener('change', update)
    }, [query])
    return matches
}

export interface DateTimeValue {
    start: Date
    end: Date
    range: DateTimeRange
}

export interface DateTimeApplyValue extends DateTimeValue {
    /** Set only when the "Include time" toggle is rendered (`showTimeToggle`). */
    includesTime?: boolean
}

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

function valueForSelection(selection: DateRangeSelection, now: Date, weekStartsOn: 0 | 1): DateTimeValue {
    if (selection.kind === 'custom') {
        return { start: selection.start, end: selection.end, range: CUSTOM_RANGE }
    }
    if (selection.kind === 'rolling') {
        return { start: rollingStart(selection.count, selection.unit, now), end: now, range: CUSTOM_RANGE }
    }
    return { ...fixedRange(selection.name, now, weekStartsOn), range: CUSTOM_RANGE }
}

function selectionKeyOf(selection: DateRangeSelection): string {
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

export interface DateTimePickerProps {
    /** Staged range seed; not needed when `selection` drives the picker. */
    value?: DateTimeValue
    onApply: (value: DateTimeApplyValue) => void
    onCancel?: () => void
    minDate?: Date
    maxDate?: Date
    dateFormat?: DateFormatOrder
    weekStartsOn?: Day
    onDateTimeSettings?: () => void
    compact?: boolean
    /** Quick-range presets to offer. Defaults to `quickRanges`; `CUSTOM_RANGE` entries are filtered out. */
    ranges?: DateTimeRange[]
    /** Presets panel: chips + "In the last" stepper + named periods beside the calendar, replacing
     *  the quick-range list. Chip and stepper picks fire `onSelectionChange` immediately; calendar
     *  picks stay staged until Apply. */
    selection?: DateRangeSelection
    onSelectionChange?: (selection: DateRangeSelection) => void
    shortChips?: DateRangeChip[]
    namedChips?: string[]
    presetsSide?: 'left' | 'right'
    /** When true (default) the calendar hides behind the panel's "Custom range…" row; when false it
     *  is always visible and the panel renders in a narrow single-column style. */
    collapsibleCalendar?: boolean
    /** Extra host rows at the bottom of the presets panel (under "Custom range…"). */
    presetsFooter?: React.ReactNode
    portalProps?: DataAttributeProps
    /** Hide the "Choose date range / Quick ranges" header band when embedding in a host surface. */
    showHeader?: boolean
    /** Day-granular mode: hides the time segments and "Now", and drops time from the footer readout. */
    showTime?: boolean
    /** Render the "Include time" toggle (mirrors `DatePicker`); `showTime` seeds it. */
    showTimeToggle?: boolean
    onIncludeTimeChange?: (includeTime: boolean) => void
    className?: string
}


export function DateTimePicker({
    value: valueProp,
    onApply,
    onCancel,
    minDate,
    maxDate: maxDateProp,
    dateFormat = 'MDY',
    weekStartsOn,
    onDateTimeSettings,
    compact = false,
    ranges = quickRanges,
    selection,
    onSelectionChange,
    shortChips = DEFAULT_SHORT_CHIPS,
    namedChips = DEFAULT_NAMED_CHIPS,
    presetsSide = 'left',
    collapsibleCalendar = true,
    presetsFooter,
    portalProps,
    showHeader = true,
    showTime: showTimeProp = true,
    showTimeToggle = false,
    onIncludeTimeChange,
    className,
}: DateTimePickerProps): React.ReactElement {
    const panelMode = selection !== undefined
    const presetRanges = panelMode ? [] : ranges.filter((r) => r.id !== CUSTOM_RANGE.id)
    const hasPresets = presetRanges.length > 0
    const maxDate = maxDateProp ?? new Date()
    const hasExplicitMaxDate = maxDateProp !== undefined
    // The second calendar only renders at `lg`; below it (and in compact) there's
    // a single calendar, so the "can't pick the sibling's month" constraint shouldn't apply.
    const isLargeScreen = useMediaQuery(LG_QUERY)
    const twoCalendars = !compact && isLargeScreen
    // In collapsible panel mode the calendar starts hidden behind the panel's "Custom range…" row.
    const [calendarOpen, setCalendarOpen] = React.useState(!panelMode || !collapsibleCalendar)
    const [includeTime, setIncludeTime] = React.useState<boolean>(showTimeProp)
    const includeTimeId = React.useId()
    const showTime = showTimeToggle ? includeTime : showTimeProp
    const weekStart01: 0 | 1 = weekStartsOn === Day.SUNDAY ? 0 : 1
    // `now` is frozen per selection so the derived seed stays time-stable across re-renders.
    const selectionKey = selection ? selectionKeyOf(selection) : ''
    const panelNow = React.useMemo(() => new Date(), [selectionKey]) // eslint-disable-line react-hooks/exhaustive-deps
    const value = selection ? valueForSelection(selection, panelNow, weekStart01) : (valueProp as DateTimeValue)
    const [start, setStart] = React.useState<Date>(value.start)
    const [end, setEnd] = React.useState<Date>(value.end)
    const [range, setRange] = React.useState<DateTimeRange>(value.range)
    const [lastSet, setLastSet] = React.useState<'start' | 'end' | null>(null)
    const [rightViewing, setRightViewing] = React.useState<Date>(value.end)
    const [leftViewing, setLeftViewing] = React.useState<Date>(subMonths(value.end, 1))

    // Preset picks commit through the host and come back as a changed `selection`;
    // re-seed the staged range (compared by time) so the calendar preview follows.
    const seedKey = `${value.start.getTime()}-${value.end.getTime()}-${value.range.id}`
    const seededKey = React.useRef(seedKey)
    React.useEffect(() => {
        if (!panelMode || seededKey.current === seedKey) {
            return
        }
        seededKey.current = seedKey
        setStart(value.start)
        setEnd(value.end)
        setRange(value.range)
        setLastSet(null)
        setRightViewing(value.end)
        setLeftViewing(subMonths(value.end, 1))
    }, [panelMode, seedKey, value])

    const handleSelect = (date: Date): void => {
        const newStart = startOfDay(date)
        const newEnd = endOfDay(date)

        if (newStart.getTime() < start.getTime()) {
            // Before current start — extend start backward, keep end
            setStart(newStart)
            setLastSet('start')
        } else if (newEnd.getTime() > end.getTime()) {
            // After current end — extend end forward, keep start
            setEnd(newEnd)
            setLastSet('end')
        } else if (lastSet === 'start') {
            // Inside range and start was just set — pull end inward
            setEnd(newEnd)
            setLastSet('end')
        } else if (lastSet === 'end') {
            // Inside range and end was just set — pull start inward
            setStart(newStart)
            setLastSet('start')
        } else {
            // No recent edge — collapse to clicked day
            setStart(newStart)
            setEnd(newEnd)
        }
        setRange(CUSTOM_RANGE)
    }

    // Move the visible calendar(s) so an edited date stays in view. With two
    // calendars, start drives the left and end the right; with one, the single
    // (right) calendar follows whichever edge changed.
    const revealStart = (date: Date): void => {
        const month = new Date(getYear(date), getMonth(date), 1)
        if (twoCalendars) {
            setLeftViewing(month)
        } else {
            setRightViewing(month)
        }
    }
    const revealEnd = (date: Date): void => {
        setRightViewing(new Date(getYear(date), getMonth(date), 1))
    }

    const handleStartChange = (next: Date): void => {
        if (start.getTime() === next.getTime()) {
            return
        }
        setRange(CUSTOM_RANGE)
        setLastSet('start')
        if (next.getTime() > end.getTime()) {
            setStart(end)
            setEnd(next)
            revealEnd(next)
        } else {
            setStart(next)
            revealStart(next)
        }
    }

    const handleEndChange = (next: Date): void => {
        if (end.getTime() === next.getTime()) {
            return
        }
        setRange(CUSTOM_RANGE)
        setLastSet('end')
        if (next.getTime() < start.getTime()) {
            setEnd(start)
            setStart(next)
            revealStart(next)
        } else {
            setEnd(next)
            revealEnd(next)
        }
    }

    const handleNow = (): void => {
        const now = new Date()
        if (start.getTime() > now.getTime()) {
            setStart(now)
        }
        setEnd(now)
        setLastSet('end')
        revealEnd(now)
    }

    const handleIncludeTimeChange = (next: boolean): void => {
        setIncludeTime(next)
        onIncludeTimeChange?.(next)
    }

    const handleQuickRange = (next: DateTimeRange): void => {
        const now = new Date()
        const nextStart = next.rangeSetter(now)
        const nextEnd = next.endSetter?.(now) ?? now
        setStart(nextStart)
        setEnd(nextEnd)
        setRange(next)
        setLastSet(null)
        setRightViewing(nextEnd)
        setLeftViewing(subMonths(nextEnd, 1))
    }

    const handleApply = (): void => {
        onApply({ start, end, range, ...(showTimeToggle ? { includesTime: includeTime } : {}) })
        if (panelMode && collapsibleCalendar) {
            setCalendarOpen(false)
        }
    }

    const handleCancel = (): void => {
        if (panelMode && collapsibleCalendar) {
            setCalendarOpen(false)
        }
        onCancel?.()
    }

    const dateTimeFormat = showTime ? DATE_TIME_FORMATS[dateFormat] : DATE_FORMATS[dateFormat]
    const presentationalStart = format(start, dateTimeFormat)
    const presentationalEnd = format(end, dateTimeFormat)

    const rolling: RelativeRangeValue =
        selection?.kind === 'rolling' ? { count: selection.count, unit: selection.unit } : { count: 7, unit: 'days' }

    const presetsPanel = selection && (
        <div className="flex h-full w-56 flex-col">
            <div className={cn('gap-1 px-2 pt-2 pb-1.5', 'grid grid-cols-3')}>
                {shortChips.map(({ label, selection: chip }) => (
                    <Button
                        key={label}
                        variant="outline"
                        size="sm"
                        className={CHIP_CLASSES}
                        aria-selected={chipSelected(chip, selection)}
                        title={chipTitle(chip, panelNow, weekStart01)}
                        onClick={() => onSelectionChange?.(chip)}
                        data-attr={`date-composer-short-${label.toLowerCase()}`}
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
                        title={chipTitle({ kind: 'fixed', name }, panelNow, weekStart01)}
                        onClick={() => onSelectionChange?.({ kind: 'fixed', name })}
                        data-attr={`date-composer-fixed-${name.toLowerCase().replace(/\s+/g, '-')}`}
                    >
                        {name}
                    </Button>
                ))}
            </div>
            {(collapsibleCalendar || presetsFooter) && (
                <div className="mt-auto flex flex-col gap-px border-t border-border p-1">
                    {collapsibleCalendar && (
                        <Button
                            variant="default"
                            size="sm"
                            left
                            className="w-full"
                            aria-expanded={calendarOpen}
                            onClick={() => setCalendarOpen((open) => !open)}
                            data-attr="date-composer-custom-range"
                        >
                            Custom range…
                            <ChevronRight className={cn('ms-auto transition-transform', calendarOpen && 'rotate-90')} />
                        </Button>
                    )}
                    {presetsFooter}
                </div>
            )}
        </div>
    )

    return (
        <div
            className={cn(
                'bg-card text-foreground rounded-lg shadow-md ring-1 ring-foreground/10 overflow-hidden',
                compact ? 'w-[15rem]' : panelMode ? 'w-max' : 'w-[15rem] lg:w-full max-w-[42rem]',
                className
            )}
            data-attr="date-time-picker"
        >
            {/* Headers */}
            {!compact && showHeader && calendarOpen && (
                <div className={hasPresets ? 'hidden lg:grid lg:grid-cols-[minmax(0,1fr)_9rem]' : 'hidden lg:grid'}>
                    <div className="flex items-center gap-2 px-2 py-1 bg-muted/30 border-b border-border rounded-tl-lg">
                        <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Choose date range</span>
                        {(minDate || hasExplicitMaxDate) && (
                            <div className="flex items-center gap-1 ml-auto">
                                {minDate && <Badge variant="default" className="text-[10px] px-1.5 py-0">Min: {format(minDate, 'MMM d, yy')}</Badge>}
                                {minDate && hasExplicitMaxDate && <span className="text-[10px] text-muted-foreground"><ArrowRight className="size-3" /></span>}
                                {hasExplicitMaxDate && <Badge variant="default" className="text-[10px] px-1.5 py-0">Max: {format(maxDate, 'MMM d, yy')}</Badge>}
                            </div>
                        )}
                    </div>
                    {hasPresets && (
                        <div className="flex justify-start px-2 py-1 bg-muted/30 border-b border-l border-border rounded-tr-lg">
                            <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Quick ranges</span>
                        </div>
                    )}
                </div>
            )}

            {/* Body */}
            <div className={panelMode
                ? calendarOpen
                    ? presetsSide === 'left'
                        ? 'flex flex-col lg:grid lg:grid-cols-[auto_minmax(0,1fr)]'
                        : 'flex flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_auto]'
                    : 'flex flex-col'
                : compact || !hasPresets
                    ? 'flex flex-col'
                    : 'flex flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_9rem]'
            }>
                {/* Presets panel — DOM-first so it stacks on top below lg; `order` places it at lg */}
                {presetsPanel && (
                    <div
                        className={cn(
                            calendarOpen && 'border-b border-border lg:border-b-0',
                            calendarOpen && (presetsSide === 'left' ? 'lg:border-r' : 'lg:order-1 lg:border-l')
                        )}
                    >
                        {presetsPanel}
                    </div>
                )}
                {/* Calendars column */}
                <div className={cn(compact ? 'order-1' : 'order-1 lg:order-none', !calendarOpen && 'hidden')}>
                    {/* Inputs */}
                    {!compact && (
                        <div className="hidden lg:flex justify-center items-center px-3 pt-3 pb-1">
                            <div className="flex items-center gap-1.5">
                                {onDateTimeSettings && (
                                    <Button
                                        size="icon-xs"
                                        onClick={onDateTimeSettings}
                                        aria-label="Date and time settings"
                                        title="Date and time settings"
                                        className="text-muted-foreground hover:text-foreground"
                                    >
                                        <SettingsIcon />
                                    </Button>
                                )}
                                <SegmentedDateInput date={start} maxDate={maxDate} onChange={handleStartChange} dateFormat={dateFormat} showTime={showTime} />
                                <span className="text-xs text-muted-foreground">to</span>
                                <SegmentedDateInput date={end} maxDate={maxDate} onChange={handleEndChange} dateFormat={dateFormat} showTime={showTime} />
                                {showTime && (
                                    <Button
                                        variant="link"
                                        size="xs"
                                        onClick={handleNow}
                                        aria-label="Set end to now"
                                        title="Set end to now"
                                    >
                                        Now
                                    </Button>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Calendars */}
                    <div className={compact
                        ? 'flex flex-col justify-between'
                        : 'flex flex-col lg:flex-row justify-between'
                    }>
                        {!compact && (
                            <div className="p-2 hidden lg:block">
                                <Calendar
                                    defaultViewing={leftViewing}
                                    startDate={start}
                                    endDate={end}
                                    minDate={minDate}
                                    maxDate={maxDate}
                                    onSelect={handleSelect}
                                    onViewChange={setLeftViewing}
                                    siblingViewing={rightViewing}
                                    weekStartsOn={weekStartsOn}
                                />
                            </div>
                        )}
                        <div className="p-2">
                            <Calendar
                                defaultViewing={rightViewing}
                                startDate={start}
                                endDate={end}
                                minDate={minDate}
                                maxDate={maxDate}
                                onSelect={handleSelect}
                                onViewChange={setRightViewing}
                                siblingViewing={twoCalendars ? leftViewing : undefined}
                                weekStartsOn={weekStartsOn}
                            />
                        </div>
                    </div>
                </div>

                {/* Quick ranges column */}
                {hasPresets && (
                <div className={compact
                    ? 'order-0 border-b border-border'
                    : 'order-0 lg:order-none lg:relative lg:border-l lg:border-border border-b border-border lg:border-b-0'
                }>
                    <ScrollArea className={compact ? 'w-full' : 'w-full lg:absolute lg:inset-0'}>
                        <ul className={compact
                            ? 'flex flex-row p-2 gap-px max-h-[320px]'
                            : 'flex flex-row lg:flex-col p-2 gap-px max-h-[320px]'
                        }>
                            {presetRanges.map((quick) => (
                                <li key={quick.id} className={compact ? undefined : 'lg:w-full'}>
                                    <Button
                                        variant="default"
                                        size="sm"
                                        left
                                        className={compact
                                            ? 'whitespace-nowrap'
                                            : 'whitespace-nowrap lg:w-full lg:justify-start'
                                        }
                                        aria-selected={range.id === quick.id}
                                        aria-label={`Choose ${quick.name.toLowerCase()}`}
                                        title={quick.name}
                                        onClick={() => handleQuickRange(quick)}
                                        data-attr={`date-time-picker-quick-range-${quick.name.toLowerCase().replace(/\s+/g, '-')}`}
                                    >
                                        {quick.name}
                                    </Button>
                                </li>
                            ))}
                        </ul>
                    </ScrollArea>
                </div>
                )}
            </div>

            {showTimeToggle && calendarOpen && (
                <div className="flex items-center gap-2 px-3 py-1.5 border-t border-border">
                    <Switch
                        checked={includeTime}
                        onCheckedChange={handleIncludeTimeChange}
                        aria-label="Include time"
                        id={includeTimeId}
                        data-attr="date-time-picker-include-time"
                    />
                    <label htmlFor={includeTimeId} className="text-xs text-muted-foreground select-none">
                        Include time
                    </label>
                </div>
            )}

            {calendarOpen && <Separator />}

            {/* Actions */}
            <div className={cn('flex justify-end px-3 py-2 items-center gap-2 bg-muted/30', !calendarOpen && 'hidden')}>
                <span className="text-[10px] text-muted-foreground flex items-center gap-1 tabular-nums mr-auto">
                    {range.id === CUSTOM_RANGE.id ? <>{presentationalStart} <ArrowRight className="size-3" /> {presentationalEnd}</> : range.name}
                </span>
                {panelMode || onCancel ? (
                    <Button variant="outline" size="sm" onClick={handleCancel} aria-label="Cancel" data-attr="date-time-picker-cancel">
                        Cancel
                    </Button>
                ) : null}
                <Button
                    variant="primary"
                    size="sm"
                    aria-label="Apply date range"
                    title="Apply date range"
                    onClick={handleApply}
                    data-attr="date-time-picker-apply-date-range"
                >
                    Apply
                </Button>
            </div>
        </div>
    )
}
