import {
    addMonths,
    endOfDay,
    format,
    getDate,
    getDay,
    getDaysInMonth,
    getHours,
    getMinutes,
    getMonth,
    getYear,
    isAfter,
    isSameDay,
    isSameMonth,
    isToday,
    startOfDay,
    subMonths,
} from 'date-fns'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import * as React from 'react'

import { Button, InputGroup, InputGroupInput, ScrollArea, Separator, cn } from '@posthog/quill-primitives'

import { CUSTOM_RANGE, type DateTimeRange, quickRanges } from './date-time-ranges'
import { useCalendar } from './use-calendar'

const DATE_TIME_FORMAT = 'MM/dd/yy HH:mm:ss'
const WEEK_DAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const MONTH_NAMES = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
]

export interface DateTimeValue {
    start: Date
    end: Date
    range: DateTimeRange
}

export interface DateTimePickerProps {
    value: DateTimeValue
    onApply: (value: DateTimeValue) => void
    onCancel?: () => void
    maxDate?: Date
    className?: string
}

interface DayItemProps {
    day: Date
    startDate: Date
    endDate: Date
    viewing: Date
    maxDate: Date
    onClick: (day: Date) => void
}

function DayItem({ day, startDate, endDate, viewing, maxDate, onClick }: DayItemProps): React.ReactElement {
    const outOfMonth = !isSameMonth(day, viewing)
    const afterMax = isAfter(day, maxDate)
    const disabled = outOfMonth || afterMax

    const isStart = !disabled && isSameDay(startDate, day)
    const isEnd = !disabled && isSameDay(endDate, day)
    const sameDay = isSameDay(startDate, endDate)
    const isBetween =
        !disabled &&
        !isStart &&
        !isEnd &&
        isAfter(day, startDate) &&
        !isAfter(day, endDate)
    const today = isToday(day)

    const label = format(day, 'dd')

    return (
        <div
            data-is-between={isBetween}
            data-is-start={isStart}
            data-is-end={isEnd}
            data-is-today={today}
            data-is-same-day={sameDay}
            className={cn(
                'w-10 h-10 flex items-center justify-center',
                isBetween && 'bg-accent/30',
                isStart && !sameDay && 'bg-accent/30 rounded-l-full',
                isEnd && !sameDay && 'bg-accent/30 rounded-r-full'
            )}
        >
            <button
                type="button"
                disabled={disabled}
                aria-label={`Select ${format(day, 'PP')}`}
                title={disabled ? undefined : `Select ${format(day, 'PP')}`}
                onClick={() => onClick(day)}
                className={cn(
                    'w-full h-full rounded-full flex items-center justify-center text-xs outline-none transition-colors',
                    'focus-visible:ring-2 focus-visible:ring-ring focus-visible:relative focus-visible:z-10',
                    !disabled && !isStart && !isEnd && 'hover:bg-fill-hover text-foreground cursor-pointer',
                    (isStart || isEnd) && 'bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer',
                    today && !isStart && !isEnd && 'border border-primary',
                    disabled && 'opacity-20 cursor-default'
                )}
            >
                {label}
            </button>
        </div>
    )
}

interface CalendarProps {
    defaultViewing: Date
    startDate: Date
    endDate: Date
    maxDate: Date
    onSelect: (day: Date) => void
    onViewChange: (month: Date) => void
    siblingViewing?: Date
}

function Calendar({
    defaultViewing,
    startDate,
    endDate,
    maxDate,
    onSelect,
    onViewChange,
    siblingViewing,
}: CalendarProps): React.ReactElement {
    const { calendar, viewing, setViewing, viewPreviousMonth, viewNextMonth } = useCalendar({
        viewing: defaultViewing,
    })

    // Keep viewing in sync if parent-controlled defaultViewing changes (e.g. when
    // quick ranges reset both calendars).
    const lastDefaultRef = React.useRef(defaultViewing)
    React.useEffect(() => {
        if (!isSameMonth(lastDefaultRef.current, defaultViewing)) {
            setViewing(defaultViewing)
            lastDefaultRef.current = defaultViewing
        }
    }, [defaultViewing, setViewing])

    const handlePrev = (): void => {
        viewPreviousMonth()
        onViewChange(subMonths(viewing, 1))
    }
    const handleNext = (): void => {
        viewNextMonth()
        onViewChange(addMonths(viewing, 1))
    }

    const disableNext =
        (getMonth(viewing) === getMonth(new Date()) && getYear(viewing) === getYear(new Date())) ||
        (!!siblingViewing &&
            getMonth(siblingViewing) === getMonth(addMonths(viewing, 1)) &&
            getYear(siblingViewing) === getYear(addMonths(viewing, 1)))

    const disablePrev =
        !!siblingViewing &&
        getMonth(siblingViewing) === getMonth(subMonths(viewing, 1)) &&
        getYear(siblingViewing) === getYear(subMonths(viewing, 1))

    return (
        <div>
            <div className="flex justify-center items-center py-2 gap-4">
                <Button
                    variant="default"
                    size="icon-sm"
                    onClick={handlePrev}
                    disabled={disablePrev}
                    aria-label="Previous month"
                    title="Previous month"
                >
                    <ChevronLeft />
                </Button>
                <span className="text-xs text-muted-foreground text-center w-28 min-w-28">
                    {MONTH_NAMES[getMonth(viewing)]} {getYear(viewing)}
                </span>
                <Button
                    variant="default"
                    size="icon-sm"
                    onClick={handleNext}
                    disabled={disableNext}
                    aria-label="Next month"
                    title={disableNext ? 'Disabled' : 'Next month'}
                >
                    <ChevronRight />
                </Button>
            </div>

            <div className="grid grid-cols-7">
                {calendar[0][0].map((day) => (
                    <div
                        key={`h-${getDay(day)}`}
                        className="w-10 h-8 flex items-center justify-center text-[10px] text-muted-foreground uppercase"
                    >
                        {WEEK_DAYS[getDay(day)]}
                    </div>
                ))}
            </div>

            <div className="flex flex-col">
                {calendar[0].map((week, wi) => (
                    <div key={`w-${wi}`} className="grid grid-cols-7">
                        {week.map((day) => (
                            <DayItem
                                key={day.toISOString()}
                                day={day}
                                startDate={startDate}
                                endDate={endDate}
                                viewing={viewing}
                                maxDate={maxDate}
                                onClick={onSelect}
                            />
                        ))}
                    </div>
                ))}
            </div>
        </div>
    )
}

interface DateTimeInputProps {
    date: Date
    onChange: (date: Date) => void
}

function pad(n: number): string {
    return n < 10 ? `0${n}` : `${n}`
}

function DateTimeInput({ date, onChange }: DateTimeInputProps): React.ReactElement {
    const [touched, setTouched] = React.useState(false)
    const [month, setMonth] = React.useState(getMonth(date) + 1)
    const [day, setDay] = React.useState(getDate(date))
    const [year, setYear] = React.useState(getYear(date))
    const [hour, setHour] = React.useState(date.getHours())
    const [minute, setMinute] = React.useState(date.getMinutes())

    // Keep onChange in a ref so debounce timer depends only on values, not on
    // whether the parent passed an inline handler this render.
    const onChangeRef = React.useRef(onChange)
    React.useEffect(() => {
        onChangeRef.current = onChange
    }, [onChange])

    React.useEffect(() => {
        setMonth(getMonth(date) + 1)
        setDay(getDate(date))
        setYear(getYear(date))
        setHour(date.getHours())
        setMinute(date.getMinutes())
    }, [date])

    React.useEffect(() => {
        if (!touched) {
            return
        }
        const handle = setTimeout(() => {
            onChangeRef.current(new Date(year, month - 1, day, hour, minute))
            setTouched(false)
        }, 400)
        return () => clearTimeout(handle)
    }, [touched, month, day, year, hour, minute])

    const handleMonth = (e: React.ChangeEvent<HTMLInputElement>): void => {
        const v = Number(e.target.value)
        if (Number.isNaN(v)) {
            return
        }
        setTouched(true)
        setMonth(v >= 13 ? 12 : v)
    }
    const handleDay = (e: React.ChangeEvent<HTMLInputElement>): void => {
        const v = Number(e.target.value)
        if (Number.isNaN(v)) {
            return
        }
        const max = getDaysInMonth(new Date(year, month - 1))
        setTouched(true)
        setDay(v > max ? max : v)
    }
    const handleYear = (e: React.ChangeEvent<HTMLInputElement>): void => {
        const v = Number(e.target.value)
        if (Number.isNaN(v)) {
            return
        }
        setTouched(true)
        setYear(Number(`20${v}`))
    }
    const handleHour = (e: React.ChangeEvent<HTMLInputElement>): void => {
        const v = Number(e.target.value)
        if (Number.isNaN(v)) {
            return
        }
        setTouched(true)
        setHour(v >= 24 ? 23 : v)
    }
    const handleMinute = (e: React.ChangeEvent<HTMLInputElement>): void => {
        const v = Number(e.target.value)
        if (Number.isNaN(v)) {
            return
        }
        setTouched(true)
        setMinute(v >= 60 ? 59 : v)
    }

    // `flex-none` overrides InputGroupInput's `flex-1` so segments stay fixed-width
    // instead of each input stretching and pushing its neighbours apart. The
    // separators are plain spans (not InputGroupAddon) because addon's cva assigns
    // `order-first`/`order-last` via its `align` variant for start/end slots, which
    // unreliably fights any explicit `order-*` we'd add for middle positions.
    const segmentClass = 'w-7 flex-none text-center tabular-nums p-0'
    const separatorClass = 'text-xs text-muted-foreground select-none'

    return (
        <div className="flex items-center gap-2">
            <InputGroup className="w-auto px-1.5">
                <InputGroupInput
                    aria-label="Month"
                    value={pad(month)}
                    onChange={handleMonth}
                    className={segmentClass}
                    maxLength={2}
                />
                <span className={separatorClass}>/</span>
                <InputGroupInput
                    aria-label="Day"
                    value={pad(day)}
                    onChange={handleDay}
                    className={segmentClass}
                    maxLength={2}
                />
                <span className={separatorClass}>/</span>
                <InputGroupInput
                    aria-label="Year"
                    value={String(year).slice(-2)}
                    onChange={handleYear}
                    className={segmentClass}
                    maxLength={2}
                />
            </InputGroup>

            <InputGroup className="w-auto px-1.5">
                <InputGroupInput
                    aria-label="Hour"
                    value={pad(hour)}
                    onChange={handleHour}
                    className={segmentClass}
                    maxLength={2}
                />
                <span className={separatorClass}>:</span>
                <InputGroupInput
                    aria-label="Minute"
                    value={pad(minute)}
                    onChange={handleMinute}
                    className={segmentClass}
                    maxLength={2}
                />
            </InputGroup>
        </div>
    )
}

export function DateTimePicker({
    value,
    onApply,
    onCancel,
    maxDate = new Date(),
    className,
}: DateTimePickerProps): React.ReactElement {
    const [start, setStart] = React.useState<Date>(value.start)
    const [end, setEnd] = React.useState<Date>(value.end)
    const [range, setRange] = React.useState<DateTimeRange>(value.range)
    const [lastSet, setLastSet] = React.useState<'start' | 'end'>('end')
    const [rightViewing, setRightViewing] = React.useState<Date>(value.end)
    const [leftViewing, setLeftViewing] = React.useState<Date>(subMonths(value.end, 1))

    const handleSelect = (date: Date): void => {
        const now = new Date()
        const hours = getHours(now)
        const minutes = getMinutes(now)
        const newDate = new Date(date)
        newDate.setHours(hours, minutes)

        const settingStart = lastSet === 'end'

        if (settingStart) {
            if (newDate.getTime() < start.getTime() || newDate.getTime() > end.getTime()) {
                setStart(newDate)
                setEnd(newDate)
            } else {
                setStart(newDate)
            }
            setLastSet('start')
        } else {
            if (newDate.getTime() === end.getTime()) {
                setStart(startOfDay(newDate))
                setEnd(endOfDay(newDate))
            } else if (newDate.getTime() < start.getTime()) {
                setStart(newDate)
                setEnd(newDate)
                setLastSet('start')
            } else {
                setEnd(newDate)
                setLastSet('end')
            }
        }
        setRange(CUSTOM_RANGE)
    }

    const handleStartChange = (next: Date): void => {
        if (start.getTime() === next.getTime()) {
            return
        }
        setRange(CUSTOM_RANGE)
        if (end.getTime() > next.getTime()) {
            setStart(next)
        }
    }

    const handleEndChange = (next: Date): void => {
        if (end.getTime() === next.getTime()) {
            return
        }
        setRange(CUSTOM_RANGE)
        if (start.getTime() < next.getTime()) {
            setEnd(next)
        }
    }

    const handleNow = (): void => {
        const now = new Date()
        if (start.getTime() > now.getTime()) {
            setStart(now)
        }
        setEnd(now)
    }

    const handleQuickRange = (next: DateTimeRange): void => {
        const now = new Date()
        const nextStart = next.rangeSetter(now)
        setStart(nextStart)
        setEnd(now)
        setRange(next)
        setRightViewing(now)
        setLeftViewing(subMonths(now, 1))
    }

    const presentationalStart = format(start, DATE_TIME_FORMAT)
    const presentationalEnd = format(end, DATE_TIME_FORMAT)

    // Responsive layout is driven by the card's own width via container queries, not
    // viewport width — so dropping the picker into a narrow Popover collapses it to
    // the stacked layout automatically regardless of window size. `min-w-[19rem]`
    // is a floor so flex parents without definite width can't collapse the card to
    // min-content (which would break the calendar's grid-cols-7 layout).
    return (
        <div
            className={cn(
                '@container bg-popover text-popover-foreground rounded-lg shadow-md ring-1 ring-foreground/10',
                'w-full min-w-[19rem] max-w-[49rem]',
                className
            )}
        >
            {/* Headers */}
            <div className="hidden @[49rem]:grid @[49rem]:grid-cols-[minmax(0,1fr)_10.625rem]">
                <div className="flex justify-end px-4 py-2 bg-muted/30 border-b border-border rounded-tl-lg">
                    <span className="text-xs text-muted-foreground">Custom</span>
                </div>
                <div className="flex justify-end px-4 py-2 bg-muted/30 border-b border-l border-border rounded-tr-lg">
                    <span className="text-xs text-muted-foreground">Quick ranges</span>
                </div>
            </div>

            {/* Body */}
            <div className="flex flex-col @[49rem]:grid @[49rem]:grid-cols-[minmax(0,1fr)_10.625rem]">
                {/* Calendars column */}
                <div className="order-1 @[49rem]:order-none">
                    {/* Inputs */}
                    <div className="hidden @[49rem]:flex justify-center items-center p-4 pb-1">
                        <div className="flex items-center gap-2">
                            <DateTimeInput date={start} onChange={handleStartChange} />
                            <span className="text-xs text-muted-foreground">to</span>
                            <DateTimeInput date={end} onChange={handleEndChange} />
                            <Button
                                variant="link"
                                size="xs"
                                onClick={handleNow}
                                aria-label="Set end to now"
                                title="Set end to now"
                            >
                                Now
                            </Button>
                        </div>
                    </div>

                    {/* Calendars */}
                    <div className="flex flex-col @[49rem]:flex-row justify-between">
                        <div className="p-3 hidden @[49rem]:block">
                            <Calendar
                                defaultViewing={leftViewing}
                                startDate={start}
                                endDate={end}
                                maxDate={maxDate}
                                onSelect={handleSelect}
                                onViewChange={setLeftViewing}
                                siblingViewing={rightViewing}
                            />
                        </div>
                        <div className="p-3">
                            <Calendar
                                defaultViewing={rightViewing}
                                startDate={start}
                                endDate={end}
                                maxDate={maxDate}
                                onSelect={handleSelect}
                                onViewChange={setRightViewing}
                                siblingViewing={leftViewing}
                            />
                        </div>
                    </div>
                </div>

                {/* Quick ranges column
                 * Wide layout: cell is `@[49rem]:relative`; ScrollArea is absolutely
                 * positioned so the grid cell takes height from the calendar sibling
                 * (inputs row + calendars row combined) and the list scrolls inside.
                 * Narrow layout: ScrollArea in normal flow with flex-row content and
                 * horizontal scroll inside the card. */}
                <div className="order-0 @[49rem]:order-none @[49rem]:relative @[49rem]:border-l @[49rem]:border-border border-b border-border @[49rem]:border-b-0">
                    <ScrollArea className="w-full @[49rem]:absolute @[49rem]:inset-0">
                        <ul className="flex flex-row @[49rem]:flex-col p-3 gap-1 max-h-[388px]">
                            {quickRanges.slice(1).map((quick) => (
                                <li key={quick.id} className="@[49rem]:w-full">
                                    <Button
                                        variant="default"
                                        size="sm"
                                        left
                                        className="whitespace-nowrap @[49rem]:w-full @[49rem]:justify-start"
                                        aria-selected={range.id === quick.id}
                                        aria-label={`Choose ${quick.name.toLowerCase()}`}
                                        title={quick.name}
                                        onClick={() => handleQuickRange(quick)}
                                    >
                                        {quick.name}
                                    </Button>
                                </li>
                            ))}
                        </ul>
                    </ScrollArea>
                </div>
            </div>

            <Separator />

            {/* Actions */}
            <div className="flex justify-end p-4 items-center gap-4 bg-muted/30">
                <span className="text-xs text-muted-foreground">
                    {range.name === 'Custom' ? `${presentationalStart} to ${presentationalEnd}` : range.name}
                </span>
                {onCancel ? (
                    <Button variant="default" size="sm" onClick={onCancel} aria-label="Cancel">
                        Cancel
                    </Button>
                ) : null}
                <Button
                    variant="primary"
                    size="sm"
                    className="w-[6.5rem]"
                    aria-label="Apply date range"
                    title="Apply date range"
                    onClick={() => onApply({ start, end, range })}
                >
                    Apply
                </Button>
            </div>
        </div>
    )
}
