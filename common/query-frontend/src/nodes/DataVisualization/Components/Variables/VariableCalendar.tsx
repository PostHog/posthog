import { useState } from 'react'

import { LemonCalendarSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

const valueIncludesTime = (value: string | null | undefined): boolean => /\d{2}:\d{2}(:\d{2})?/.test(value ?? '')

export const VariableCalendar = ({
    value,
    rawValue,
    updateVariable,
}: {
    value: dayjs.Dayjs
    rawValue?: string | null
    updateVariable: (date: string) => void
}): JSX.Element => {
    const [calendarTime, setCalendarTime] = useState(() => valueIncludesTime(rawValue))

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
