import { useState } from 'react'

import { LemonCalendarSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

export const VariableCalendar = ({
    value,
    updateVariable,
}: {
    value: dayjs.Dayjs
    updateVariable: (date: string) => void
}): JSX.Element => {
    const [calendarTime, setCalendarTime] = useState(() => {
        // Check if the date string contains time information (HH:mm or HH:mm:ss)
        return /\d{2}:\d{2}(:\d{2})?/.test(value.format('YYYY-MM-DD HH:mm:00'))
    })

    return (
        <LemonCalendarSelect
            value={value}
            onChange={(date) => {
                updateVariable(
                    calendarTime ? (date?.format('YYYY-MM-DD HH:mm:00') ?? '') : (date?.format('YYYY-MM-DD') ?? '')
                )
            }}
            showTimeToggle={true}
            granularity={calendarTime ? 'minute' : 'day'}
            onToggleTime={(value) => setCalendarTime(value)}
        />
    )
}
