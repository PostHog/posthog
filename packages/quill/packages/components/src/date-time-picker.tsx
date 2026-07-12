import { endOfDay, format, getMonth, getYear, startOfDay, subMonths } from 'date-fns'
import { ArrowRight, SettingsIcon } from 'lucide-react'
import * as React from 'react'

import { Badge, Button, ScrollArea, Separator, cn } from '@posthog/quill-primitives'

import { Calendar } from './calendar-grid'
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

export interface DateTimePickerProps {
    value: DateTimeValue
    onApply: (value: DateTimeValue) => void
    onCancel?: () => void
    minDate?: Date
    maxDate?: Date
    dateFormat?: DateFormatOrder
    weekStartsOn?: Day
    onDateTimeSettings?: () => void
    compact?: boolean
    /** Quick-range presets to offer. Defaults to `quickRanges`; `CUSTOM_RANGE` entries are filtered out. */
    ranges?: DateTimeRange[]
    /** Hide the "Choose date range / Quick ranges" header band when embedding in a host surface. */
    showHeader?: boolean
    /** Host content in the actions bar, next to the range readout (e.g. an exclusions control). */
    footerExtra?: React.ReactNode
    /** Day-granular mode: hides the time segments and "Now", and drops time from the footer readout. */
    showTime?: boolean
    /** Presets-first mode: quick ranges render as a left-hand list and apply immediately on click
     * (`onApply` fires with the computed range); the calendar, with its staged Apply flow, is
     * revealed in place by a "Custom range…" row. Opens on the calendar when `value.range` is
     * `CUSTOM_RANGE`. Ignored in `compact`. */
    presetsFirst?: boolean
    className?: string
}


export function DateTimePicker({
    value,
    onApply,
    onCancel,
    minDate,
    maxDate: maxDateProp,
    dateFormat = 'MDY',
    weekStartsOn,
    onDateTimeSettings,
    compact = false,
    ranges = quickRanges,
    showHeader = true,
    footerExtra,
    showTime = true,
    presetsFirst = false,
    className,
}: DateTimePickerProps): React.ReactElement {
    const presetRanges = ranges.filter((r) => r.id !== CUSTOM_RANGE.id)
    const presetsFirstMode = presetsFirst && !compact
    const hasPresets = presetRanges.length > 0 && !presetsFirstMode
    const [customExpanded, setCustomExpanded] = React.useState(value.range.id === CUSTOM_RANGE.id)
    const showCalendarArea = !presetsFirstMode || customExpanded
    const maxDate = maxDateProp ?? new Date()
    const hasExplicitMaxDate = maxDateProp !== undefined
    // The second calendar only renders at `lg`; below it (and in compact) there's
    // a single calendar, so the "can't pick the sibling's month" constraint shouldn't apply.
    const isLargeScreen = useMediaQuery(LG_QUERY)
    const twoCalendars = !compact && isLargeScreen
    const [start, setStart] = React.useState<Date>(value.start)
    const [end, setEnd] = React.useState<Date>(value.end)
    const [range, setRange] = React.useState<DateTimeRange>(value.range)
    const [lastSet, setLastSet] = React.useState<'start' | 'end' | null>(null)
    const [rightViewing, setRightViewing] = React.useState<Date>(value.end)
    const [leftViewing, setLeftViewing] = React.useState<Date>(subMonths(value.end, 1))

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

    const applyQuickRange = (next: DateTimeRange): void => {
        const now = new Date()
        handleQuickRange(next)
        onApply({ start: next.rangeSetter(now), end: next.endSetter?.(now) ?? now, range: next })
    }

    const dateTimeFormat = showTime ? DATE_TIME_FORMATS[dateFormat] : DATE_FORMATS[dateFormat]
    const presentationalStart = format(start, dateTimeFormat)
    const presentationalEnd = format(end, dateTimeFormat)

    return (
        <div
            className={cn(
                'bg-card text-foreground rounded-lg shadow-md ring-1 ring-foreground/10 overflow-hidden',
                compact
                    ? 'w-[15rem]'
                    : presetsFirstMode && !customExpanded
                      ? 'w-max'
                      : presetsFirstMode
                        ? 'w-[15rem] lg:w-full max-w-[53rem]'
                        : 'w-[15rem] lg:w-full max-w-[42rem]',
                className
            )}
        >
            {/* Headers */}
            {!compact && showHeader && (
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
            <div className={cn(
                compact || !hasPresets ? 'flex flex-col' : 'flex flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_9rem]',
                presetsFirstMode && customExpanded && 'flex-row'
            )}>
                {/* Presets-first list column */}
                {presetsFirstMode && (
                    <div className={cn('flex flex-col', customExpanded && 'shrink-0 border-r border-border')}>
                        <ul className="flex max-h-[400px] flex-col gap-px overflow-y-auto p-1">
                            {presetRanges.map((quick) => (
                                <li key={quick.id} className="w-full">
                                    <Button
                                        variant="default"
                                        left
                                        className="w-full justify-start whitespace-nowrap"
                                        aria-selected={range.id === quick.id}
                                        aria-label={`Choose ${quick.name.toLowerCase()}`}
                                        title={quick.name}
                                        onClick={() => applyQuickRange(quick)}
                                        data-attr={`date-time-picker-quick-range-${quick.name.toLowerCase().replace(/\s+/g, '-')}`}
                                    >
                                        {quick.name}
                                    </Button>
                                </li>
                            ))}
                            <li className="w-full">
                                <Button
                                    variant="default"
                                    left
                                    className="w-full justify-start whitespace-nowrap"
                                    aria-selected={customExpanded || range.id === CUSTOM_RANGE.id}
                                    onClick={() => setCustomExpanded((prev) => !prev)}
                                    data-attr="date-time-picker-custom-range"
                                >
                                    Custom range…
                                </Button>
                            </li>
                        </ul>
                    </div>
                )}

                {/* Calendars column */}
                {showCalendarArea && (
                <div className={compact ? 'order-1' : 'order-1 lg:order-none'}>
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
                )}

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

            {(showCalendarArea || footerExtra) && <Separator />}

            {/* Actions */}
            {!showCalendarArea && footerExtra && (
                <div className="flex items-center px-3 py-2 bg-muted/30">{footerExtra}</div>
            )}
            {showCalendarArea && (
            <div className="flex justify-end px-3 py-2 items-center gap-2 bg-muted/30">
                <div className="mr-auto flex items-center gap-2">
                    {/* The lg inputs row shows the same staged range, so the readout yields to it */}
                    <span
                        className={cn(
                            'text-[10px] text-muted-foreground flex items-center gap-1 tabular-nums',
                            !compact && 'lg:hidden'
                        )}
                    >
                        {range.id === CUSTOM_RANGE.id ? <>{presentationalStart} <ArrowRight className="size-3" /> {presentationalEnd}</> : range.name}
                    </span>
                    {footerExtra}
                </div>
                {onCancel || presetsFirstMode ? (
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={presetsFirstMode ? () => setCustomExpanded(false) : onCancel}
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
                    onClick={() => onApply({ start, end, range })}
                    data-attr="date-time-picker-apply-date-range"
                >
                    Apply
                </Button>
            </div>
            )}
        </div>
    )
}
