import { endOfDay, format, getMonth, getYear, startOfDay, subMonths } from 'date-fns'
import { ArrowRight, SettingsIcon } from 'lucide-react'
import * as React from 'react'

import { Badge, Button, ScrollArea, Separator, Switch, cn } from '@posthog/quill-primitives'

import { Calendar } from './calendar-grid'
import {
    DateRangePresetsPanel,
    selectionKeyOf,
    valueForSelection,
    type DataAttributeProps,
    type DateRangeChip,
    type DateRangeSelection,
} from './date-range-presets-panel'
import { CUSTOM_RANGE, type DateTimeRange, quickRanges } from './date-time-ranges'
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
    /** When true (default) the calendar hides behind the panel's "Custom range…" row. */
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
    shortChips,
    namedChips,
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

    const presetsPanel = selection && (
        <DateRangePresetsPanel
            selection={selection}
            onSelectionChange={onSelectionChange}
            shortChips={shortChips}
            namedChips={namedChips}
            now={panelNow}
            weekStartsOn={weekStart01}
            calendarOpen={calendarOpen}
            onCalendarOpenChange={collapsibleCalendar ? setCalendarOpen : undefined}
            footer={presetsFooter}
            portalProps={portalProps}
        />
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
                        <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
                            Choose date range
                        </span>
                        {(minDate || hasExplicitMaxDate) && (
                            <div className="flex items-center gap-1 ml-auto">
                                {minDate && (
                                    <Badge variant="default" className="text-[10px] px-1.5 py-0">
                                        Min: {format(minDate, 'MMM d, yy')}
                                    </Badge>
                                )}
                                {minDate && hasExplicitMaxDate && (
                                    <span className="text-[10px] text-muted-foreground">
                                        <ArrowRight className="size-3" />
                                    </span>
                                )}
                                {hasExplicitMaxDate && (
                                    <Badge variant="default" className="text-[10px] px-1.5 py-0">
                                        Max: {format(maxDate, 'MMM d, yy')}
                                    </Badge>
                                )}
                            </div>
                        )}
                    </div>
                    {hasPresets && (
                        <div className="flex justify-start px-2 py-1 bg-muted/30 border-b border-l border-border rounded-tr-lg">
                            <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
                                Quick ranges
                            </span>
                        </div>
                    )}
                </div>
            )}

            {/* Body */}
            <div
                className={
                    panelMode
                        ? calendarOpen
                            ? presetsSide === 'left'
                                ? 'flex flex-col lg:grid lg:grid-cols-[auto_minmax(0,1fr)]'
                                : 'flex flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_auto]'
                            : 'flex flex-col'
                        : compact || !hasPresets
                          ? 'flex flex-col'
                          : 'flex flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_9rem]'
                }
            >
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
                                <SegmentedDateInput
                                    date={start}
                                    maxDate={maxDate}
                                    onChange={handleStartChange}
                                    dateFormat={dateFormat}
                                    showTime={showTime}
                                />
                                <span className="text-xs text-muted-foreground">to</span>
                                <SegmentedDateInput
                                    date={end}
                                    maxDate={maxDate}
                                    onChange={handleEndChange}
                                    dateFormat={dateFormat}
                                    showTime={showTime}
                                />
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
                    <div
                        className={
                            compact ? 'flex flex-col justify-between' : 'flex flex-col lg:flex-row justify-between'
                        }
                    >
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
                    <div
                        className={
                            compact
                                ? 'order-0 border-b border-border'
                                : 'order-0 lg:order-none lg:relative lg:border-l lg:border-border border-b border-border lg:border-b-0'
                        }
                    >
                        <ScrollArea className={compact ? 'w-full' : 'w-full lg:absolute lg:inset-0'}>
                            <ul
                                className={
                                    compact
                                        ? 'flex flex-row p-2 gap-px max-h-[320px]'
                                        : 'flex flex-row lg:flex-col p-2 gap-px max-h-[320px]'
                                }
                            >
                                {presetRanges.map((quick) => (
                                    <li key={quick.id} className={compact ? undefined : 'lg:w-full'}>
                                        <Button
                                            variant="default"
                                            size="sm"
                                            left
                                            className={
                                                compact
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
                    {range.id === CUSTOM_RANGE.id ? (
                        <>
                            {presentationalStart} <ArrowRight className="size-3" /> {presentationalEnd}
                        </>
                    ) : (
                        range.name
                    )}
                </span>
                {panelMode || onCancel ? (
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={handleCancel}
                        aria-label="Cancel"
                        data-attr="date-time-picker-cancel"
                    >
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
