import './LemonCalendar.scss'
import { useEffect, useState } from 'react'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'
import { LemonButton, LemonButtonProps } from 'lib/components/LemonButton'
import { IconChevronLeft, IconChevronRight } from 'lib/components/icons'
import clsx from 'clsx'
import { getAppContext } from 'lib/utils/getAppContext'

export interface LemonCalendarProps {
    /** Fired if a calendar cell is clicked */
    onDateClick?: (date: string, month: string) => void
    /** YYYY-MM-xx to specify the month that is shown */
    leftmostMonth?: string | null
    /** Called if the user changed the month in the calendar */
    onLeftmostMonthChanged?: (date: string) => void
    /** Use custom LemonButton properties for each date */
    getLemonButtonProps?: (opts: GetLemonButtonPropsOpts) => LemonButtonProps
    /** Number of months */
    months?: number
    /** First day of the week (defaults to 1 = Monday) */
    weekStart?: number
}

export interface GetLemonButtonPropsOpts {
    date: string
    month: string
    props: LemonButtonProps
    dayIndex: number
    weekIndex: number
}

const dayLabels = ['su', 'mo', 'tu', 'we', 'th', 'fr', 'sa']

export function LemonCalendar(props: LemonCalendarProps): JSX.Element {
    const months = Math.max(props.months ?? 1, 1)
    const weekStart = props.weekStart ?? getAppContext()?.week_start ?? 1
    const today = dayjs().startOf('day')
    const [leftmostMonth, setLeftmostMonth] = useState(props.leftmostMonth ?? dayjs().format('YYYY-MM-DD'))
    useEffect(() => {
        if (props.leftmostMonth && props.leftmostMonth !== leftmostMonth) {
            setLeftmostMonth(props.leftmostMonth)
        }
    }, [props.leftmostMonth])

    return (
        <div className="LemonCalendar flex items-start gap-4" data-attr="lemon-calendar">
            {range(0, months).map((month) => {
                const startOfMonth = (leftmostMonth ? dayjs(leftmostMonth) : dayjs())
                    .add(month, 'month')
                    .startOf('month')
                const endOfMonth = (leftmostMonth ? dayjs(leftmostMonth) : dayjs()).add(month, 'month').endOf('month')
                const stringMonth = startOfMonth.format('YYYY-MM-DD')
                const firstDay = startOfMonth.subtract((startOfMonth.day() - weekStart + 7) % 7, 'days')
                const lastDay = endOfMonth.add((((weekStart + 6) % 7) - endOfMonth.day() + 7) % 7, 'days')
                const weeks = lastDay.diff(firstDay, 'week') + 1
                const showLeftMonth = month === 0
                const showRightMonth = month + 1 === months

                return (
                    <table className="LemonCalendar__month" key={month} data-attr="lemon-calendar-month">
                        <thead>
                            <tr>
                                <th className="relative">
                                    {showLeftMonth && (
                                        <LemonButton
                                            status="stealth"
                                            fullWidth
                                            data-attr="lemon-calendar-month-previous"
                                            className="absolute-left"
                                            onClick={() => {
                                                const newDate = dayjs(leftmostMonth)
                                                    .subtract(1, 'month')
                                                    .format('YYYY-MM-DD')
                                                setLeftmostMonth(newDate)
                                                props.onLeftmostMonthChanged?.(newDate)
                                            }}
                                        >
                                            <IconChevronLeft />
                                        </LemonButton>
                                    )}
                                </th>
                                <th className="relative" colSpan={5}>
                                    <LemonButton
                                        status="muted"
                                        fullWidth
                                        center
                                        data-attr={`lemon-calendar-month-title-${month}`}
                                        className="text-xs font-bold text-muted uppercase cursor-default"
                                    >
                                        {startOfMonth.format('MMMM')} {startOfMonth.year()}
                                    </LemonButton>{' '}
                                </th>
                                <th className="relative">
                                    {showRightMonth && (
                                        <LemonButton
                                            status="stealth"
                                            fullWidth
                                            data-attr="lemon-calendar-month-next"
                                            className="absolute-right"
                                            onClick={() => {
                                                const newDate = dayjs(leftmostMonth)
                                                    .add(1, 'month')
                                                    .format('YYYY-MM-DD')
                                                setLeftmostMonth(newDate)
                                                props.onLeftmostMonthChanged?.(newDate)
                                            }}
                                        >
                                            <IconChevronRight />
                                        </LemonButton>
                                    )}
                                </th>
                            </tr>
                            <tr>
                                {range(0, 7).map((day) => (
                                    <th key={day} className="py-2 text-xs font-bold text-muted-alt uppercase">
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
                                        const stringDate = date.format('YYYY-MM-DD')
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
                                                date: stringDate,
                                                month: stringMonth,
                                                props: defaultProps,
                                            }) ?? defaultProps
                                        return (
                                            <td key={day}>
                                                <LemonButton
                                                    fullWidth
                                                    center
                                                    status="stealth"
                                                    data-attr="lemon-calendar-day"
                                                    onClick={() => props.onDateClick?.(stringDate, stringMonth)}
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
        </div>
    )
}
