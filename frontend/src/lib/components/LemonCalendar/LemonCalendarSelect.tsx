import { LemonCalendar } from 'lib/components/LemonCalendar/LemonCalendar'
import React from 'react'
import { dayjs } from 'lib/dayjs'

interface LemonCalendarSelectProps {
    value?: string | null
    onChange: (date: string) => void
    months?: number
}

export function LemonCalendarSelect({ value, onChange, months }: LemonCalendarSelectProps): JSX.Element {
    const parsedValue = value ? dayjs(value).format('YYYY-MM-DD') : undefined
    return (
        <LemonCalendar
            onClick={onChange}
            firstMonth={parsedValue}
            months={months}
            getLemonButtonProps={(date, _, defaultProps) => {
                if (date === parsedValue) {
                    return { ...defaultProps, status: 'primary', type: 'primary' }
                }
                return defaultProps
            }}
        />
    )
}
