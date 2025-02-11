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
    const [calendarTime, setCalendarTime] = useState(
        variable.default_value ? dayjs(variable.default_value).format('HH:mm:00') !== '' : false
    )
    const [date, setDate] = useState(showDefault ? dayjs(variable.default_value) : dayjs(variable.value))

    return (
        <LemonCalendarSelect
            value={date}
            onChange={(date) => {
                setDate(date)
                updateVariable(
                    calendarTime ? date?.format('YYYY-MM-DD HH:mm:00') ?? '' : date?.format('YYYY-MM-DD 00:00:00') ?? ''
                )
            }}
            showTimeToggle={true}
            granularity={calendarTime ? 'minute' : 'day'}
            onToggleTime={(value) => setCalendarTime(value)}
        />
    )
}
