import {
    addMonths,
    addYears,
    format,
    getDay,
    getMonth,
    getYear,
    isAfter,
    isSameDay,
    isSameMonth,
    isToday,
    startOfToday,
    subMonths,
} from 'date-fns'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import * as React from 'react'

import { Button, Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue, cn } from '@posthog/quill-primitives'

import { Day, useCalendar } from './use-calendar'

export const POSTHOG_START_DATE = new Date(2020, 0, 23)
export const WEEK_DAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
export const MONTH_NAMES = [
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

function dayOnly(date: Date): Date {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

interface DayItemProps {
    day: Date
    startDate: Date
    endDate: Date
    viewing: Date
    minDate?: Date
    maxDate?: Date
    onClick: (day: Date) => void
}

export function DayItem({
    day,
    startDate,
    endDate,
    viewing,
    minDate,
    maxDate,
    onClick,
}: DayItemProps): React.ReactElement {
    const outOfMonth = !isSameMonth(day, viewing)
    const dayDate = dayOnly(day)
    const afterMax = maxDate ? dayDate.getTime() > dayOnly(maxDate).getTime() : false
    const beforeMin = minDate ? dayDate.getTime() < dayOnly(minDate).getTime() : false
    const disabled = outOfMonth || afterMax || beforeMin

    const isStart = !disabled && isSameDay(startDate, day)
    const isEnd = !disabled && isSameDay(endDate, day)
    const sameDay = isSameDay(startDate, endDate)
    const isBetween = !disabled && !isStart && !isEnd && isAfter(day, startDate) && !isAfter(day, endDate)
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
                'w-8 h-8 flex items-center justify-center',
                isBetween && 'bg-fill-selected',
                isStart && !sameDay && 'bg-fill-selected rounded-l-full',
                isEnd && !sameDay && 'bg-fill-selected rounded-r-full'
            )}
        >
            <Button
                variant={isStart || isEnd ? 'primary' : 'default'}
                size="icon-sm"
                disabled={disabled}
                aria-label={`Select ${format(day, 'PP')}`}
                title={disabled ? undefined : `Select ${format(day, 'PP')}`}
                onClick={() => onClick(day)}
                className={cn(
                    'w-full h-full !rounded-full p-0 text-[11px] tabular-nums',
                    today && !isStart && !isEnd && 'border border-primary',
                    disabled && 'opacity-20'
                )}
            >
                {label}
            </Button>
        </div>
    )
}

interface CalendarProps {
    defaultViewing: Date
    startDate: Date
    endDate: Date
    minDate?: Date
    maxDate?: Date
    onSelect: (day: Date) => void
    onViewChange: (month: Date) => void
    siblingViewing?: Date
    weekStartsOn?: Day
}

export function Calendar({
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

    const floorDate = minDate && minDate.getTime() > POSTHOG_START_DATE.getTime() ? minDate : POSTHOG_START_DATE
    const minYearVal = getYear(floorDate)
    const minMonthAtMinYear = getMonth(floorDate)
    const floorKey = minYearVal * 12 + minMonthAtMinYear
    // An unbounded picker still needs a finite month list for the Select, so navigation
    // (not selection) caps ten years out when no maxDate is given.
    const ceilDate = maxDate ?? addYears(startOfToday(), 10)
    const ceilKey = getYear(ceilDate) * 12 + getMonth(ceilDate)
    const viewingKey = getYear(viewing) * 12 + getMonth(viewing)

    const disableNext =
        viewingKey >= ceilKey ||
        (!!siblingViewing &&
            getMonth(siblingViewing) === getMonth(addMonths(viewing, 1)) &&
            getYear(siblingViewing) === getYear(addMonths(viewing, 1)))

    const disablePrev =
        viewingKey <= floorKey ||
        (!!siblingViewing &&
            getMonth(siblingViewing) === getMonth(subMonths(viewing, 1)) &&
            getYear(siblingViewing) === getYear(subMonths(viewing, 1)))
    const maxYearVal = getYear(ceilDate)
    const maxMonthAtMaxYear = getMonth(ceilDate)
    const currentYear = getYear(viewing)
    const currentMonth = getMonth(viewing)

    const monthKey = (year: number, month: number): number => year * 12 + month
    const currentKey = monthKey(currentYear, currentMonth)
    const siblingKey = siblingViewing ? monthKey(getYear(siblingViewing), getMonth(siblingViewing)) : null

    const monthOptions: { key: number; year: number; month: number }[] = []
    for (let y = minYearVal; y <= maxYearVal; y++) {
        const startMonth = y === minYearVal ? minMonthAtMinYear : 0
        const endMonth = y === maxYearVal ? maxMonthAtMaxYear : 11
        for (let m = startMonth; m <= endMonth; m++) {
            monthOptions.push({ key: monthKey(y, m), year: y, month: m })
        }
    }

    const handleMonthYearSelect = (next: number): void => {
        const year = Math.floor(next / 12)
        const month = next % 12
        const nextDate = new Date(year, month, 1)
        setViewing(nextDate)
        onViewChange(nextDate)
    }

    return (
        <div>
            <div className="flex justify-center items-center py-1 gap-1">
                <Button
                    variant="default"
                    size="icon-sm"
                    onClick={handlePrev}
                    disabled={disablePrev}
                    aria-label="Previous month"
                    title={disablePrev ? 'Disabled' : 'Previous month'}
                    className="disabled:cursor-not-allowed"
                >
                    <ChevronLeft />
                </Button>
                <Select
                    value={currentKey}
                    onValueChange={(v) => {
                        if (v !== null) {
                            handleMonthYearSelect(v)
                        }
                    }}
                >
                    <SelectTrigger size="sm" aria-label="Month and year" className="h-6 px-2 text-xs">
                        <SelectValue>{(v: number) => `${MONTH_NAMES[v % 12]} ${Math.floor(v / 12)}`}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {monthOptions.map(({ key, year, month }) => (
                                <SelectItem key={key} value={key} disabled={key === siblingKey}>
                                    {MONTH_NAMES[month]} {year}
                                </SelectItem>
                            ))}
                        </SelectGroup>
                    </SelectContent>
                </Select>
                <Button
                    variant="default"
                    size="icon-sm"
                    onClick={handleNext}
                    disabled={disableNext}
                    aria-label="Next month"
                    title={disableNext ? 'Disabled' : 'Next month'}
                    className="disabled:cursor-not-allowed"
                >
                    <ChevronRight />
                </Button>
            </div>

            <div className="grid grid-cols-7">
                {calendar[0][0].map((day) => (
                    <div
                        key={`h-${getDay(day)}`}
                        className="w-8 h-6 flex items-center justify-center text-[10px] text-muted-foreground uppercase"
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
