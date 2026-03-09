import { useState } from 'react'

import { LemonCalendarSelectInput } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { PropertyFilterValue } from '~/types'

interface PropertyFilterDateBetweenProps {
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
}

const dateFormat = 'YYYY-MM-DD'

/**
 * A "between" filter for date properties that renders two date pickers
 * (min date and max date) instead of two number inputs.
 */
export function PropertyFilterDateBetween({ value, onSet }: PropertyFilterDateBetweenProps): JSX.Element {
    // Value is stored as [min, max] array
    const parsed = Array.isArray(value) ? value : []
    const [minValue, setMinValue] = useState<dayjs.Dayjs | undefined>(
        parsed[0] ? dayjs(String(parsed[0])) : undefined
    )
    const [maxValue, setMaxValue] = useState<dayjs.Dayjs | undefined>(
        parsed[1] ? dayjs(String(parsed[1])) : undefined
    )
    const [minOpen, setMinOpen] = useState(false)
    const [maxOpen, setMaxOpen] = useState(false)

    const updateValue = (newMin: dayjs.Dayjs | undefined, newMax: dayjs.Dayjs | undefined): void => {
        const minStr = newMin?.format(dateFormat) ?? ''
        const maxStr = newMax?.format(dateFormat) ?? ''
        onSet([minStr, maxStr])
    }

    return (
        <div className="flex items-center gap-2">
            <LemonCalendarSelectInput
                value={minValue}
                format={dateFormat}
                visible={minOpen}
                onClickOutside={() => setMinOpen(false)}
                onChange={(selectedDate) => {
                    setMinValue(selectedDate)
                    updateValue(selectedDate, maxValue)
                    setMinOpen(false)
                }}
                onClose={() => setMinOpen(false)}
                granularity="day"
                buttonProps={{
                    'data-attr': 'prop-val-date-min',
                    onClick: () => setMinOpen(true),
                    children: minValue ? minValue.format(dateFormat) : 'Start date',
                }}
            />
            <span className="font-medium">and</span>
            <LemonCalendarSelectInput
                value={maxValue}
                format={dateFormat}
                visible={maxOpen}
                onClickOutside={() => setMaxOpen(false)}
                onChange={(selectedDate) => {
                    setMaxValue(selectedDate)
                    updateValue(minValue, selectedDate)
                    setMaxOpen(false)
                }}
                onClose={() => setMaxOpen(false)}
                granularity="day"
                buttonProps={{
                    'data-attr': 'prop-val-date-max',
                    onClick: () => setMaxOpen(true),
                    children: maxValue ? maxValue.format(dateFormat) : 'End date',
                }}
            />
        </div>
    )
}
