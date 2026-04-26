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
import { ArrowRight, ChevronLeft, ChevronRight, SettingsIcon } from 'lucide-react'
import * as React from 'react'

import { Badge, Button, InputGroup, InputGroupNumberInput, ScrollArea, Separator, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, cn } from '@posthog/quill-primitives'

import { CUSTOM_RANGE, type DateTimeRange, quickRanges } from './date-time-ranges'
import { Day, useCalendar } from './use-calendar'

const DATE_TIME_FORMATS: Record<DateFormatOrder, string> = {
    MDY: 'MM/dd/yy HH:mm:ss',
    DMY: 'dd/MM/yy HH:mm:ss',
    YMD: 'yy-MM-dd HH:mm:ss',
}

const DATE_FORMAT_LABELS: Record<DateFormatOrder, string> = {
    MDY: 'MM/DD/YY',
    DMY: 'DD/MM/YY',
    YMD: 'YY-MM-DD',
}
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

export type DateFormatOrder = 'MDY' | 'DMY' | 'YMD'

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
    className?: string
}

interface DayItemProps {
    day: Date
    startDate: Date
    endDate: Date
    viewing: Date
    minDate?: Date
    maxDate: Date
    onClick: (day: Date) => void
}

function DayItem({ day, startDate, endDate, viewing, minDate, maxDate, onClick }: DayItemProps): React.ReactElement {
    const outOfMonth = !isSameMonth(day, viewing)
    const dayDate = new Date(day.getFullYear(), day.getMonth(), day.getDate())
    const maxDay = new Date(maxDate.getFullYear(), maxDate.getMonth(), maxDate.getDate())
    const afterMax = dayDate.getTime() > maxDay.getTime()
    const beforeMin = minDate
        ? dayDate.getTime() < new Date(minDate.getFullYear(), minDate.getMonth(), minDate.getDate()).getTime()
        : false
    const disabled = outOfMonth || afterMax || beforeMin

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
    minDate?: Date
    maxDate: Date
    onSelect: (day: Date) => void
    onViewChange: (month: Date) => void
    siblingViewing?: Date
    weekStartsOn?: Day
}

function Calendar({
    defaultViewing,
    startDate,
    endDate,
    minDate,
    maxDate,
    onSelect,
    onViewChange,
    siblingViewing,
    weekStartsOn,
}: CalendarProps): React.ReactElement {
    const { calendar, viewing, setViewing, viewPreviousMonth, viewNextMonth } = useCalendar({
        viewing: defaultViewing,
        weekStartsOn,
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
                                minDate={minDate}
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
    maxDate: Date
    onChange: (date: Date) => void
    dateFormat: DateFormatOrder
}

const PAD_2 = { minimumIntegerDigits: 2 } as const

function DateTimeInput({ date, maxDate, onChange, dateFormat }: DateTimeInputProps): React.ReactElement {
    const [month, setMonth] = React.useState(getMonth(date) + 1)
    const [day, setDay] = React.useState(getDate(date))
    const [year, setYear] = React.useState(getYear(date) % 100)
    const [hour, setHour] = React.useState(getHours(date))
    const [minute, setMinute] = React.useState(getMinutes(date))

    const onChangeRef = React.useRef(onChange)
    React.useEffect(() => {
        onChangeRef.current = onChange
    }, [onChange])

    React.useEffect(() => {
        setMonth(getMonth(date) + 1)
        setDay(getDate(date))
        setYear(getYear(date) % 100)
        setHour(getHours(date))
        setMinute(getMinutes(date))
    }, [date])

    const touched = React.useRef(false)
    React.useEffect(() => {
        if (!touched.current) {
            return
        }
        const handle = setTimeout(() => {
            onChangeRef.current(new Date(2000 + year, month - 1, day, hour, minute))
            touched.current = false
        }, 400)
        return () => clearTimeout(handle)
    }, [month, day, year, hour, minute])

    const set = (setter: React.Dispatch<React.SetStateAction<number>>) => (v: number | null) => {
        if (v === null) {
            return
        }
        touched.current = true
        setter(v)
    }

    const segmentClass = 'w-7 flex-none text-center tabular-nums p-0'
    const separatorClass = 'text-xs text-muted-foreground select-none'
    const sep = dateFormat === 'YMD' ? '-' : '/'

    const maxYear = getYear(maxDate) % 100
    const atMaxYear = year === maxYear
    const maxMonth = atMaxYear ? getMonth(maxDate) + 1 : 12
    const atMaxMonth = atMaxYear && month === maxMonth
    const maxDay = atMaxMonth ? getDate(maxDate) : getDaysInMonth(new Date(2000 + year, month - 1))

    const monthSegment = (
        <InputGroupNumberInput
            key="month"
            aria-label="Month"
            value={month}
            onValueChange={set(setMonth)}
            min={1}
            max={maxMonth}
            format={PAD_2}
            className={segmentClass}
        />
    )
    const daySegment = (
        <InputGroupNumberInput
            key="day"
            aria-label="Day"
            value={day}
            onValueChange={set(setDay)}
            min={1}
            max={maxDay}
            format={PAD_2}
            className={segmentClass}
        />
    )
    const yearSegment = (
        <InputGroupNumberInput
            key="year"
            aria-label="Year"
            value={year}
            onValueChange={set(setYear)}
            min={0}
            max={maxYear}
            format={PAD_2}
            className={segmentClass}
        />
    )

    const dateSegments =
        dateFormat === 'DMY'
            ? [daySegment, monthSegment, yearSegment]
            : dateFormat === 'YMD'
                ? [yearSegment, monthSegment, daySegment]
                : [monthSegment, daySegment, yearSegment]

    return (
        <TooltipProvider>
            <div className="flex items-center gap-2">
                <Tooltip>
                    <TooltipTrigger render={
                        <InputGroup className="w-auto px-1.5">
                            {dateSegments.map((segment, i) => (
                                <React.Fragment key={i}>
                                    {i > 0 && <span className={separatorClass}>{sep}</span>}
                                    {segment}
                                </React.Fragment>
                            ))}
                        </InputGroup>
                    }/>
                    <TooltipContent>
                        {DATE_FORMAT_LABELS[dateFormat]}
                    </TooltipContent>
                </Tooltip>


                <InputGroup className="w-auto px-1.5">
                    <InputGroupNumberInput
                        aria-label="Hour"
                        value={hour}
                        onValueChange={set(setHour)}
                        min={0}
                        max={23}
                        format={PAD_2}
                        className={segmentClass}
                    />
                    <span className={separatorClass}>:</span>
                    <InputGroupNumberInput
                        aria-label="Minute"
                        value={minute}
                        onValueChange={set(setMinute)}
                        min={0}
                        max={59}
                        format={PAD_2}
                        className={segmentClass}
                    />
                </InputGroup>
            </div>
        </TooltipProvider>

    )
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
    className,
}: DateTimePickerProps): React.ReactElement {
    const maxDate = maxDateProp ?? new Date()
    const hasExplicitMaxDate = maxDateProp !== undefined
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
        if (next.getTime() > end.getTime()) {
            setStart(end)
            setEnd(next)
        } else {
            setStart(next)
        }
    }

    const handleEndChange = (next: Date): void => {
        if (end.getTime() === next.getTime()) {
            return
        }
        setRange(CUSTOM_RANGE)
        if (next.getTime() < start.getTime()) {
            setEnd(start)
            setStart(next)
        } else {
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

    const dateTimeFormat = DATE_TIME_FORMATS[dateFormat]
    const presentationalStart = format(start, dateTimeFormat)
    const presentationalEnd = format(end, dateTimeFormat)

    return (
        <div
            className={cn(
                'bg-popover text-popover-foreground rounded-lg shadow-md ring-1 ring-foreground/10',
                compact ? 'w-[19rem]' : 'w-[19rem] lg:w-full max-w-[49rem]',
                className
            )}
        >
            {/* Headers */}
            {!compact && (
                <div className="hidden lg:grid lg:grid-cols-[minmax(0,1fr)_10.625rem]">
                    <div className="flex items-center gap-2 px-2 py-2 bg-muted/30 border-b border-border rounded-tl-lg">
                        <span className="text-xs text-muted-foreground">Custom</span>
                        {(minDate || hasExplicitMaxDate) && (
                            <div className="flex items-center gap-1 ml-auto">
                                {minDate && <Badge variant="default" className="text-[10px] px-1.5 py-0">Min date: {format(minDate, 'MMM d, yy')}</Badge>}
                                {minDate && hasExplicitMaxDate && <span className="text-[10px] text-muted-foreground"><ArrowRight className="size-3" /></span>}
                                {hasExplicitMaxDate && <Badge variant="default" className="text-[10px] px-1.5 py-0">Max date: {format(maxDate, 'MMM d, yy')}</Badge>}
                            </div>
                        )}
                    </div>
                    <div className="flex justify-start px-2 py-2 bg-muted/30 border-b border-l border-border rounded-tr-lg">
                        <span className="text-xs text-muted-foreground">Quick ranges</span>
                    </div>
                </div>
            )}

            {/* Body */}
            <div className={compact
                ? 'flex flex-col'
                : 'flex flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_10.625rem]'
            }>
                {/* Calendars column */}
                <div className={compact ? 'order-1' : 'order-1 lg:order-none'}>
                    {/* Inputs */}
                    {!compact && (
                        <div className="hidden lg:flex justify-center items-center p-4 pb-1">
                            <div className="flex items-center gap-2">
                                {onDateTimeSettings && (
                                    <Button
                                        size="icon-sm"
                                        onClick={onDateTimeSettings}
                                        aria-label="Date and time settings"
                                        title="Date and time settings"
                                        className="text-muted-foreground hover:text-foreground"
                                    >
                                        <SettingsIcon className="w-4 h-4" />
                                    </Button>
                                )}
                                <DateTimeInput date={start} maxDate={maxDate} onChange={handleStartChange} dateFormat={dateFormat} />
                                <span className="text-xs text-muted-foreground">to</span>
                                <DateTimeInput date={end} maxDate={maxDate} onChange={handleEndChange} dateFormat={dateFormat} />
                                <Button
                                    variant="link"
                                    size="sm"
                                    onClick={handleNow}
                                    aria-label="Set end to now"
                                    title="Set end to now"
                                >
                                    Now
                                </Button>
                            </div>
                        </div>
                    )}

                    {/* Calendars */}
                    <div className={compact
                        ? 'flex flex-col justify-between'
                        : 'flex flex-col lg:flex-row justify-between'
                    }>
                        {!compact && (
                            <div className="p-3 hidden lg:block">
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
                        <div className="p-3">
                            <Calendar
                                defaultViewing={rightViewing}
                                startDate={start}
                                endDate={end}
                                minDate={minDate}
                                maxDate={maxDate}
                                onSelect={handleSelect}
                                onViewChange={setRightViewing}
                                siblingViewing={compact ? undefined : leftViewing}
                                weekStartsOn={weekStartsOn}
                            />
                        </div>
                    </div>
                </div>

                {/* Quick ranges column */}
                <div className={compact
                    ? 'order-0 border-b border-border'
                    : 'order-0 lg:order-none lg:relative lg:border-l lg:border-border border-b border-border lg:border-b-0'
                }>
                    <ScrollArea className={compact ? 'w-full' : 'w-full lg:absolute lg:inset-0'}>
                        <ul className={compact
                            ? 'flex flex-row p-3 gap-px max-h-[388px]'
                            : 'flex flex-row lg:flex-col p-3 gap-px max-h-[388px]'
                        }>
                            {quickRanges.slice(1).map((quick) => (
                                <li key={quick.id} className={compact ? undefined : 'lg:w-full'}>
                                    <Button
                                        variant="default"
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
            </div>

            <Separator />

            {/* Actions */}
            <div className="flex justify-end p-4 items-center gap-2 bg-muted/30">
                <span className="text-xs text-muted-foreground flex items-center gap-1 tabular-nums">
                    {range.name === 'Custom' ? <>{presentationalStart} <ArrowRight className="size-3" /> {presentationalEnd}</> : range.name}
                </span>
                {onCancel ? (
                    <Button variant="outline" onClick={onCancel} aria-label="Cancel" data-attr="date-time-picker-cancel">
                        Cancel
                    </Button>
                ) : null}
                <Button
                    variant="primary"
                    aria-label="Apply date range"
                    title="Apply date range"
                    onClick={() => onApply({ start, end, range })}
                    data-attr="date-time-picker-apply-date-range"
                >
                    Apply
                </Button>
            </div>
        </div>
    )
}
