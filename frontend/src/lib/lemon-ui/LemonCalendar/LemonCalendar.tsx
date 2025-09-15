import './LemonCalendar.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { Ref, forwardRef, useEffect, useState } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { range } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

export interface LemonCalendarProps {
    /** Fired if a calendar cell is clicked */
    onDateClick?: (date: dayjs.Dayjs) => void
    /** First day of the leftmost month on display. */
    leftmostMonth?: dayjs.Dayjs
    /** Called if the user changed the month in the calendar */
    onLeftmostMonthChanged?: (date: dayjs.Dayjs) => void
    /** Use custom LemonButton properties for each date */
    getLemonButtonProps?: (opts: GetLemonButtonPropsOpts) => LemonButtonProps
    /** Use custom LemonButton properties for each date */
    getLemonButtonTimeProps?: (opts: GetLemonButtonTimePropsOpts) => LemonButtonProps
    /** Number of months */
    months?: number
    /** 0 or unset for Sunday, 1 for Monday. */
    weekStartDay?: number
    /** Set the time granularity of the calendar */
    granularity?: 'day' | 'hour' | 'minute'
}

export interface GetLemonButtonPropsOpts {
    date: dayjs.Dayjs
    props: LemonButtonProps
    dayIndex: number
    weekIndex: number
}
export interface GetLemonButtonTimePropsOpts {
    unit: 'h' | 'm' | 'a'
    value: number | string
}

const dayLabels = ['su', 'mo', 'tu', 'we', 'th', 'fr', 'sa']

export const LemonCalendar = forwardRef(function LemonCalendar(
    { granularity = 'day', ...props }: LemonCalendarProps,
    ref: Ref<HTMLDivElement>
): JSX.Element {
    const { weekStartDay: teamWeekStartDay } = useValues(teamLogic)

    const months = Math.max(props.months ?? 1, 1)
    const weekStartDay = props.weekStartDay ?? teamWeekStartDay
    const today = dayjs().startOf('day')

    const [leftmostMonth, setLeftmostMonth] = useState<dayjs.Dayjs>((props.leftmostMonth ?? today).startOf('month'))
    useEffect(() => {
        if (props.leftmostMonth && props.leftmostMonth.isSame(leftmostMonth, 'd')) {
            setLeftmostMonth(props.leftmostMonth)
        }
    }, [props.leftmostMonth]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div
            ref={ref}
            className={clsx(
                'LemonCalendar relative flex items-start gap-4 tabular-nums',
                `LemonCalendar--${granularity}`
            )}
            data-attr="lemon-calendar"
        >
            {range(0, months).map((month) => {
                const startOfMonth = leftmostMonth.add(month, 'month').startOf('month')
                // need to add a day because of https://github.com/iamkun/dayjs/issues/2007
                // calling endOf('month') on startOfMonth goes to the end of the previous month
                const endOfMonth = startOfMonth.add(1, 'day').endOf('month')
                const firstDay = startOfMonth.subtract((startOfMonth.day() - weekStartDay + 7) % 7, 'days')
                const lastDay = endOfMonth.add((((weekStartDay + 6) % 7) - endOfMonth.day() + 7) % 7, 'days')
                const weeks = lastDay.diff(firstDay, 'week') + 1
                const showLeftMonth = month === 0
                const showRightMonth = month + 1 === months

                return (
                    <table className="LemonCalendar__month" key={month} data-attr="lemon-calendar-month">
                        <thead>
                            <tr className="LemonCalendar__month-header">
                                <th className="relative">
                                    {showLeftMonth && (
                                        <LemonButton
                                            fullWidth
                                            data-attr="lemon-calendar-month-previous"
                                            className="absolute-left"
                                            onClick={() => {
                                                const newDate = leftmostMonth.subtract(1, 'month')
                                                setLeftmostMonth(newDate)
                                                props.onLeftmostMonthChanged?.(newDate)
                                            }}
                                            icon={<IconChevronLeft />}
                                        />
                                    )}
                                </th>
                                <th
                                    className="relative font-title font-semibold text-secondary uppercase cursor-default text-center"
                                    data-attr={`lemon-calendar-month-title-${month}`}
                                    colSpan={5}
                                >
                                    {startOfMonth.format('MMMM')} {startOfMonth.year()}
                                </th>
                                <th className="relative">
                                    {showRightMonth && (
                                        <LemonButton
                                            fullWidth
                                            data-attr="lemon-calendar-month-next"
                                            className="absolute-right"
                                            onClick={() => {
                                                const newDate = leftmostMonth.add(1, 'month')
                                                setLeftmostMonth(newDate)
                                                props.onLeftmostMonthChanged?.(newDate)
                                            }}
                                            icon={<IconChevronRight />}
                                        />
                                    )}
                                </th>
                            </tr>
                            <tr>
                                {range(0, 7).map((day) => (
                                    <th key={day} className="py-2 text-xs font-bold text-secondary uppercase">
                                        {dayLabels[firstDay.add(day, 'day').day()]}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {range(0, weeks).map((week) => (
                                <tr key={week} data-attr="lemon-calendar-week">
                                    {range(0, 7).map((day) => {
                                        const date = firstDay.add(week * 7 + day, 'day')
                                        const defaultProps: LemonButtonProps = {
                                            className: clsx('flex-col', {
                                                'opacity-25': date.isBefore(startOfMonth) || date.isAfter(endOfMonth),
                                                LemonCalendar__today: date.isSame(today, 'd'),
                                            }),
                                        }

                                        const buttonProps =
                                            props.getLemonButtonProps?.({
                                                dayIndex: day,
                                                weekIndex: week,
                                                date,
                                                props: defaultProps,
                                            }) ?? defaultProps
                                        return (
                                            <td key={day}>
                                                <LemonButton
                                                    fullWidth
                                                    center
                                                    data-attr="lemon-calendar-day"
                                                    onClick={() => props.onDateClick?.(date)}
                                                    {...buttonProps}
                                                >
                                                    {date.date()}
                                                </LemonButton>
                                            </td>
                                        )
                                    })}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )
            })}
            {granularity != 'day' && (
                <div className="LemonCalendar__time absolute top-0 bottom-0 right-0 flex divide-x border-l">
                    <ScrollableShadows direction="vertical">
                        {[12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((hour) => {
                            const buttonProps = props.getLemonButtonTimeProps?.({
                                unit: 'h',
                                value: hour,
                            })

                            return (
                                <LemonButton fullWidth key={hour} {...buttonProps}>
                                    <span className="w-full text-center px-2">{String(hour).padStart(2, '0')}</span>
                                </LemonButton>
                            )
                        })}
                        <div className="LemonCalendar__time--scroll-spacer" />
                    </ScrollableShadows>
                    {granularity === 'minute' && (
                        <ScrollableShadows direction="vertical">
                            {range(0, 60).map((minute) => {
                                const buttonProps = props.getLemonButtonTimeProps?.({
                                    unit: 'm',
                                    value: minute,
                                })
                                return (
                                    <LemonButton fullWidth key={minute} {...buttonProps}>
                                        <span className="w-full text-center px-2">
                                            {String(minute).padStart(2, '0')}
                                        </span>
                                    </LemonButton>
                                )
                            })}
                            <div className="LemonCalendar__time--scroll-spacer" />
                        </ScrollableShadows>
                    )}
                    <div>
                        <LemonButton fullWidth {...props.getLemonButtonTimeProps?.({ unit: 'a', value: 'am' })}>
                            <span className="w-full text-center">AM</span>
                        </LemonButton>
                        <LemonButton fullWidth {...props.getLemonButtonTimeProps?.({ unit: 'a', value: 'pm' })}>
                            <span className="w-full text-center">PM</span>
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
})
