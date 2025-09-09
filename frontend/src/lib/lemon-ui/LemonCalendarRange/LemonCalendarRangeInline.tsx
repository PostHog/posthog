import clsx from 'clsx'
import { useEffect, useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonCalendar } from 'lib/lemon-ui/LemonCalendar/LemonCalendar'

import { LemonCalendarRangeProps } from './LemonCalendarRange'

/** Used to calculate how many calendars fit on the screen */
const WIDTH_OF_ONE_CALENDAR_MONTH = 300
/** Number of calendars to display if `typeof window === undefined` */
const CALENDARS_IF_NO_WINDOW = 2

type RangeState = [dayjs.Dayjs | null, dayjs.Dayjs | null, 'start' | 'end']

export function LemonCalendarRangeInline({
    value,
    onChange,
    months,
}: Omit<LemonCalendarRangeProps, 'onClose'>): JSX.Element {
    // Keep a sanitised and cached copy of the selected range
    const [[rangeStart, rangeEnd, lastChanged], _setRange] = useState<RangeState>([
        value?.[0] ?? null,
        value?.[1] ?? null,
        'end',
    ])

    function setRange([rangeStart, rangeEnd, lastChanged]: RangeState): void {
        _setRange([rangeStart, rangeEnd ? rangeEnd.endOf('day') : null, lastChanged])
        if (rangeStart && rangeEnd) {
            onChange([rangeStart, rangeEnd.endOf('day')])
        }
    }

    // How many months fit on the screen, capped between 1..2
    function getMonthCount(): number {
        const width =
            typeof window === 'undefined' ? WIDTH_OF_ONE_CALENDAR_MONTH * CALENDARS_IF_NO_WINDOW : window.innerWidth
        return Math.min(Math.max(1, Math.floor(width / WIDTH_OF_ONE_CALENDAR_MONTH)), 2)
    }
    const [autoMonthCount, setAutoMonthCount] = useState(getMonthCount())
    useEffect(() => {
        const listener = (): void => {
            if (autoMonthCount !== getMonthCount()) {
                setAutoMonthCount(getMonthCount())
            }
        }
        window.addEventListener('resize', listener)
        return () => window.removeEventListener('resize', listener)
    }, [autoMonthCount])

    // What months exactly are shown on the calendar
    const shownMonths = months ?? autoMonthCount
    const rangeMonthDiff =
        rangeStart && rangeEnd ? rangeEnd.startOf('month').diff(rangeStart.startOf('month'), 'month') : 0
    const leftmostMonthForRange = (rangeStart ?? rangeEnd ?? dayjs())
        .subtract(Math.max(0, shownMonths - 1 - rangeMonthDiff), 'month')
        .startOf('month')
    const [leftmostMonth, setLeftmostMonth] = useState(leftmostMonthForRange)

    // If the range changes via props and is not in view, update the first month
    useEffect(() => {
        const lastMonthForRange = leftmostMonthForRange.add(shownMonths - 1, 'month').endOf('month')
        if (
            rangeStart &&
            rangeEnd &&
            (rangeStart.isAfter(lastMonthForRange) || rangeEnd.isBefore(leftmostMonthForRange))
        ) {
            setLeftmostMonth(leftmostMonthForRange)
        }
    }, [rangeStart, rangeEnd]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <LemonCalendar
            onDateClick={(date) => {
                if (!rangeStart && !rangeEnd) {
                    setRange([date, date, 'start'])
                } else if (rangeStart && !rangeEnd) {
                    setRange(date < rangeStart ? [date, rangeStart, 'start'] : [rangeStart, date, 'end'])
                } else if (rangeEnd && !rangeStart) {
                    setRange(date < rangeEnd ? [date, rangeEnd, 'start'] : [rangeEnd, date, 'end'])
                } else if (rangeStart && rangeEnd) {
                    if (date === rangeStart || date === rangeEnd) {
                        setRange([date, date, 'start'])
                    } else if (date < rangeStart) {
                        setRange([date, rangeEnd, 'start'])
                    } else if (date > rangeEnd) {
                        setRange([rangeStart, date, 'end'])
                    } else if (lastChanged === 'start') {
                        setRange([rangeStart, date, 'end'])
                    } else {
                        setRange([date, rangeEnd, 'start'])
                    }
                }
            }}
            leftmostMonth={leftmostMonth}
            onLeftmostMonthChanged={setLeftmostMonth}
            months={shownMonths}
            getLemonButtonProps={({ date, props, dayIndex }) => {
                if (date.isSame(rangeStart, 'd') || date.isSame(rangeEnd, 'd')) {
                    return {
                        ...props,
                        className:
                            date.isSame(rangeStart, 'd') && date.isSame(rangeEnd, 'd')
                                ? props.className
                                : clsx(
                                      props.className,
                                      {
                                          'rounded-r-none': date.isSame(rangeStart, 'd') && dayIndex < 6,
                                          'rounded-l-none': date.isSame(rangeEnd, 'd') && dayIndex > 0,
                                      },
                                      'LemonCalendar__range--boundary'
                                  ),
                        type: 'primary',
                    }
                } else if (rangeStart && rangeEnd && date > rangeStart && date < rangeEnd) {
                    return {
                        ...props,
                        className: clsx(
                            props.className,
                            dayIndex === 0 ? 'rounded-r-none' : dayIndex === 6 ? 'rounded-l-none' : 'rounded-none'
                        ),
                        active: true,
                    }
                }
                return props
            }}
        />
    )
}
