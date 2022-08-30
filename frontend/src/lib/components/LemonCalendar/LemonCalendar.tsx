import './LemonCalendar.scss'
import React, { useEffect, useState } from 'react'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'
import { LemonButton, LemonButtonProps } from 'lib/components/LemonButton'
import { IconChevronLeft, IconChevronRight } from 'lib/components/icons'
import clsx from 'clsx'

export interface LemonCalendarProps {
    /** Fired if a calendar cell is clicked */
    onDateClick?: (date: string) => void
    /** YYYY-MM-xx to specify the month that is shown */
    firstMonth?: string | null
    /** Called if the user changed the month in the calendar */
    onFirstMonthChanged?: (date: string) => void
    /** Use custom LemonButton properties for each date */
    getLemonButtonProps?: (date: string, month: string, defaultProps: LemonButtonProps) => LemonButtonProps
    /** Number of months */
    months?: number
    /** Number of weeks in each month */
    weeks?: number
}

const dayLabels = ['su', 'mo', 'tu', 'we', 'th', 'fr', 'sa']

export function LemonCalendar(props: LemonCalendarProps): JSX.Element {
    const months = Math.max(props.months ?? 1, 1)
    const today = dayjs().startOf('day')
    const [firstMonth, setFirstMonth] = useState(props.firstMonth ?? dayjs().format('YYYY-MM-DD'))
    useEffect(() => {
        if (props.firstMonth && props.firstMonth !== firstMonth) {
            setFirstMonth(props.firstMonth)
        }
    }, [props.firstMonth])

    return (
        <div className="LemonCalendar flex items-start gap-4">
            {range(0, months).map((month) => {
                const startOfMonth = (firstMonth ? dayjs(firstMonth) : dayjs()).add(month, 'month').startOf('month')
                const endOfMonth = (firstMonth ? dayjs(firstMonth) : dayjs()).add(month, 'month').endOf('month')
                const stringMonth = startOfMonth.format('YYYY-MM-DD')
                // TODO: support the easier US Sunday-first format as well
                const firstDay = startOfMonth.subtract(startOfMonth.day() === 0 ? 6 : startOfMonth.day() - 1, 'days')
                const lastDay = endOfMonth.add(endOfMonth.day() === 0 ? 0 : 7 - endOfMonth.day(), 'days')
                const weeks = props.weeks ?? lastDay.diff(firstDay, 'week') + 1
                const showLeftMonth = month === 0
                const showRightMonth = month + 1 === months

                return (
                    <table className="LemonCalendar__month" key={month}>
                        <thead>
                            <tr>
                                {showLeftMonth && (
                                    <th>
                                        <LemonButton
                                            status="stealth"
                                            fullWidth
                                            onClick={() => {
                                                const newDate = dayjs(firstMonth)
                                                    .subtract(1, 'month')
                                                    .format('YYYY-MM-DD')
                                                setFirstMonth(newDate)
                                                props.onFirstMonthChanged?.(newDate)
                                            }}
                                        >
                                            <IconChevronLeft />
                                        </LemonButton>
                                    </th>
                                )}
                                <th colSpan={7 - (showLeftMonth ? 1 : 0) - (showRightMonth ? 1 : 0)}>
                                    <LemonButton
                                        status="muted"
                                        fullWidth
                                        center
                                        className="text-xs font-bold text-muted uppercase cursor-default"
                                    >
                                        {startOfMonth.format('MMMM')} {startOfMonth.year()}
                                    </LemonButton>
                                </th>
                                {showRightMonth && (
                                    <th>
                                        <LemonButton
                                            status="stealth"
                                            fullWidth
                                            onClick={() => {
                                                const newDate = dayjs(firstMonth).add(1, 'month').format('YYYY-MM-DD')
                                                setFirstMonth(newDate)
                                                props.onFirstMonthChanged?.(newDate)
                                            }}
                                        >
                                            <IconChevronRight />
                                        </LemonButton>
                                    </th>
                                )}
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
                                <tr key={week}>
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
                                            props.getLemonButtonProps?.(stringDate, stringMonth, defaultProps) ??
                                            defaultProps
                                        return (
                                            <td key={day}>
                                                <LemonButton
                                                    fullWidth
                                                    center
                                                    status="stealth"
                                                    onClick={() => props.onDateClick?.(stringDate)}
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
