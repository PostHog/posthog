import { LemonCalendarSelect } from '@posthog/lemon-ui'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'

import { DateVariable } from '../../types'

export const VariableCalendar = ({
    variable,
    updateVariable,
    showDefault = false,
}: {
    variable: DateVariable
    updateVariable: (date: string) => void
    showDefault?: boolean
}): JSX.Element => {
    const [calendarTime, setCalendarTime] = useState(() => {
        const dateToCheck = showDefault || !variable.value ? variable.default_value : variable.value
        if (!dateToCheck) {
            return false
        }
        // Check if the date string contains time information (HH:mm or HH:mm:ss)
        return /\d{2}:\d{2}(:\d{2})?/.test(dateToCheck)
    })

    const [date, setDate] = useState(showDefault ? dayjs(variable.default_value) : dayjs(variable.value))

    return (
        <LemonCalendarSelect
            value={date}
            onChange={(date) => {
                setDate(date)
                updateVariable(
                    calendarTime ? date?.format('YYYY-MM-DD HH:mm:00') ?? '' : date?.format('YYYY-MM-DD') ?? ''
                )
            }}
            showTimeToggle={true}
            granularity={calendarTime ? 'minute' : 'day'}
            onToggleTime={(value) => setCalendarTime(value)}
        />
    )
}
