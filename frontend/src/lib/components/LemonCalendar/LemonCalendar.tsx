import './LemonCalendar.scss'
import React, { useEffect, useState } from 'react'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'
import { LemonButton, LemonButtonProps } from 'lib/components/LemonButton'
import { IconChevronLeft, IconChevronRight } from 'lib/components/icons'

export interface LemonCalendarProps {
    /** Fired if a calendar cell is clicked */
    onClick?: (date: string) => void
    /** YYYY-MM(-DD) for month that is shown, derived from "value" if absent */
    firstMonth?: string
    /** Called if the user changed the month in the calendar */
    onFirstMonthChanged?: (date: string) => void
    /** Return the classnames for a date */
    getLemonButtonProps?: (date: string, defaultProps: LemonButtonProps) => LemonButtonProps
    /** Number of months */
    months?: number
    /** Number of weeks in each month */
    weeks?: number
}

const dayLabels = ['su', 'mo', 'tu', 'we', 'th', 'fr', 'sa']

export function LemonCalendar(props: LemonCalendarProps): JSX.Element {
    const months = Math.max(props.months ?? 1, 1)
    const [firstMonth, setFirstMonth] = useState(props.firstMonth ?? dayjs().format('YYYY-MM-DD'))
    useEffect(() => {
        if (props.firstMonth && props.firstMonth !== firstMonth) {
            setFirstMonth(props.firstMonth)
        }
    }, [props.firstMonth])

    return (
        <>
            {range(0, months).map((month) => {
                const startOfMonth = (firstMonth ? dayjs(firstMonth) : dayjs()).add(month, 'month').startOf('month')
                const endOfMonth = (firstMonth ? dayjs(firstMonth) : dayjs()).add(month, 'month').endOf('month')

                // TODO: support the easier US Sunday-first format as well
                const firstDay = startOfMonth.subtract(startOfMonth.day() === 0 ? 6 : startOfMonth.day() - 1, 'days')
                const lastDay = endOfMonth.add(endOfMonth.day() === 0 ? 0 : 7 - endOfMonth.day(), 'days')
                const weeks = props.weeks ?? lastDay.diff(firstDay, 'week') + 1
                const today = dayjs().format('YYYY-MM-DD')
                const showLeftMonth = month === 0
                const showRightMonth = month + 1 === months

                return (
                    <table className="LemonCalendar" key={month}>
                        <thead>
                            <tr>
                                {showLeftMonth && (
                                    <th className="text-muted">
                                        <LemonButton
                                            status="stealth"
                                            fullWidth
                                            onClick={() => {
                                                const newDate = startOfMonth.subtract(1, 'month').format('YYYY-MM-DD')
                                                setFirstMonth(newDate)
                                                props.onFirstMonthChanged?.(newDate)
                                            }}
                                        >
                                            <IconChevronLeft />
                                        </LemonButton>
                                    </th>
                                )}
                                <th
                                    colSpan={7 - (showLeftMonth ? 1 : 0) - (showRightMonth ? 1 : 0)}
                                    className="py-2 text-xs font-bold text-muted uppercase"
                                >
                                    {startOfMonth.format('MMMM')} {startOfMonth.year()}
                                </th>
                                {showRightMonth && (
                                    <th className="text-muted">
                                        <LemonButton
                                            status="stealth"
                                            fullWidth
                                            onClick={() => {
                                                const newDate = startOfMonth.add(1, 'month').format('YYYY-MM-DD')
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
                                        const defaultProps: LemonButtonProps = {}
                                        //     const from = (rangeDateFrom ?? dayjs()).format('YYYY-MM-DD')
                                        //     console.log({ date, from: from })
                                        //     return date === (rangeDateFrom ?? dayjs()).format('YYYY-MM-DD')
                                        //         ? { status: 'primary', type: 'primary' }
                                        //         : date > now
                                        //         ? { status: 'muted', className: 'text-muted opacity-25' }
                                        //         : date > from
                                        //         ? { active: true }
                                        //         : {}
                                        // }}
                                        if (stringDate > today) {
                                            defaultProps.className = 'text-muted opacity-25'
                                        }

                                        const buttonProps = props.getLemonButtonProps
                                            ? props.getLemonButtonProps(stringDate, defaultProps)
                                            : defaultProps
                                        return (
                                            <td key={day}>
                                                <LemonButton
                                                    fullWidth
                                                    status="stealth"
                                                    onClick={() => props.onClick?.(stringDate)}
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
        </>
    )
}
