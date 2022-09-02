import { LemonCalendar } from 'lib/components/LemonCalendar/LemonCalendar'
import React, { useEffect, useState } from 'react'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'
import { formatDate, formatDateRange } from 'lib/utils'
import clsx from 'clsx'

export interface LemonCalendarRangeProps {
    value?: [string, string] | null
    onChange: (date: [string, string]) => void
    months?: number
    onClose?: () => void
    hideHeader?: boolean
    autoApply?: boolean
}

/** Used to calculate how many calendars fit on the screen */
const WIDTH_OF_ONE_CALENDAR_MONTH = 300
/** Number of calendars to display if `typeof window === undefined` */
const CALENDARS_IF_NO_WINDOW = 2

export function LemonCalendarRange({
    value,
    onChange,
    onClose,
    months,
    hideHeader,
    autoApply,
}: LemonCalendarRangeProps): JSX.Element {
    // Keep a sanitised and cached copy of the selected range
    const [valueStart, valueEnd] = [
        value?.[0] ? dayjs(value[0]).format('YYYY-MM-DD') : null,
        value?.[1] ? dayjs(value[1]).format('YYYY-MM-DD') : null,
    ]
    const [[rangeStart, rangeEnd, lastChanged], _setRange] = useState([valueStart, valueEnd, 'end' as 'start' | 'end'])

    function setRange([rangeStart, rangeEnd, lastChanged]: [string | null, string | null, 'start' | 'end']): void {
        _setRange([rangeStart, rangeEnd, lastChanged])
        if (autoApply && rangeStart && rangeEnd) {
            onChange([rangeStart, rangeEnd])
        }
    }

    // How many months fit on the screen, capped between 1..2
    function getMonthCount(): number {
        const width =
            typeof window === undefined ? WIDTH_OF_ONE_CALENDAR_MONTH * CALENDARS_IF_NO_WINDOW : window.innerWidth
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
        rangeStart && rangeEnd ? dayjs(rangeEnd).startOf('month').diff(dayjs(rangeStart).startOf('month'), 'month') : 0
    const leftmostMonthForRange = dayjs(rangeStart ?? rangeEnd ?? undefined)
        .subtract(Math.max(0, shownMonths - 1 - rangeMonthDiff), 'month')
        .startOf('month')
        .format('YYYY-MM-DD')
    const [leftmostMonth, setLeftmostMonth] = useState(leftmostMonthForRange)

    // If the range changes via props and is not in view, update the first month
    useEffect(() => {
        const lastMonthForRange = dayjs(leftmostMonthForRange)
            .add(shownMonths - 1, 'month')
            .endOf('month')
        if (
            rangeStart &&
            rangeEnd &&
            (dayjs(rangeStart).isAfter(lastMonthForRange) || dayjs(rangeEnd).isBefore(dayjs(leftmostMonthForRange)))
        ) {
            setLeftmostMonth(leftmostMonthForRange)
        }
    }, [rangeStart, rangeEnd])

    return (
        <div className="LemonCalendarRange" data-attr="lemon-calendar-range">
            {hideHeader ? null : (
                <div className="flex justify-between border-b p-2 pb-4">
                    <h3 className="mb-0">Select a fixed time period</h3>
                    {onClose && (
                        <LemonButton
                            icon={<IconClose />}
                            size="small"
                            status="stealth"
                            onClick={onClose}
                            aria-label="close"
                        />
                    )}
                </div>
            )}
            <div className="p-2">
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
                        if (date === rangeStart || date === rangeEnd) {
                            return {
                                ...props,
                                className:
                                    date === rangeStart && date === rangeEnd
                                        ? props.className
                                        : clsx(props.className, {
                                              'rounded-r-none': date === rangeStart && dayIndex < 6,
                                              'rounded-l-none': date === rangeEnd && dayIndex > 0,
                                          }),
                                status: 'primary',
                                type: 'primary',
                            }
                        } else if (rangeStart && rangeEnd && date > rangeStart && date < rangeEnd) {
                            return {
                                ...props,
                                className: clsx(
                                    props.className,
                                    dayIndex === 0
                                        ? 'rounded-r-none'
                                        : dayIndex === 6
                                        ? 'rounded-l-none'
                                        : 'rounded-none'
                                ),
                                active: true,
                            }
                        }
                        return props
                    }}
                />
            </div>
            <div className="flex space-x-2 justify-end items-center border-t p-2 pt-4">
                {shownMonths > 1 && rangeStart && rangeEnd && (
                    <div className="flex-1">
                        <span className="text-muted">Selected period:</span>{' '}
                        <span>
                            {rangeStart === rangeEnd
                                ? formatDate(dayjs(rangeStart))
                                : formatDateRange(dayjs(rangeStart), dayjs(rangeEnd))}
                        </span>
                    </div>
                )}
                {autoApply ? null : (
                    <>
                        <LemonButton type="secondary" onClick={onClose} data-attr="lemon-calendar-range-cancel">
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabled={!rangeStart || !rangeEnd}
                            onClick={rangeStart && rangeEnd ? () => onChange([rangeStart, rangeEnd]) : undefined}
                            data-attr="lemon-calendar-range-apply"
                        >
                            Apply
                        </LemonButton>
                    </>
                )}
            </div>
        </div>
    )
}
