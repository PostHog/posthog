import { useEffect, useState } from 'react'

import { LemonCalendarSelectInput } from '@posthog/lemon-ui'

import { PropertyValueProps } from 'lib/components/PropertyFilters/components/PropertyValue'
import { dayjs } from 'lib/dayjs'
import { isOperatorDate } from 'lib/utils'

import { PropertyFilterValue, PropertyOperator } from '~/types'

const dayJSMightParse = (candidateDateTimeValue: PropertyFilterValue): candidateDateTimeValue is string | number =>
    ['string', 'number'].includes(typeof candidateDateTimeValue)

const narrowToString = (candidateDateTimeValue?: PropertyFilterValue): candidateDateTimeValue is string | null =>
    typeof candidateDateTimeValue === 'string'

interface PropertyFilterDatePickerProps {
    autoFocus: boolean
    operator: PropertyOperator
    setValue: (newValue: PropertyValueProps['value']) => void
    value: string | number | null
}

const dateAndTimeFormat = 'YYYY-MM-DD HH:mm:ss'
const onlyDateFormat = 'YYYY-MM-DD'

export function PropertyFilterDatePicker({
    autoFocus,
    operator,
    setValue,
    value,
}: PropertyFilterDatePickerProps): JSX.Element {
    // if ten characters then value is YYYY-MM-DD not YYYY-MM-DD HH:mm:ss
    const valueIsYYYYMMDD = narrowToString(value) && value?.length === 10

    const [datePickerOpen, setDatePickerOpen] = useState(operator && isOperatorDate(operator) && autoFocus)
    const [datePickerValue, setDatePickerValue] = useState(dayJSMightParse(value) ? dayjs(value) : undefined)
    const [includeTimeInFilter, setIncludeTimeInFilter] = useState(!!value && !valueIsYYYYMMDD)
    const [dateFormat, setDateFormat] = useState(valueIsYYYYMMDD ? onlyDateFormat : dateAndTimeFormat)

    useEffect(() => {
        setDateFormat(includeTimeInFilter ? dateAndTimeFormat : onlyDateFormat)
    }, [includeTimeInFilter])

    return (
        <LemonCalendarSelectInput
            value={datePickerValue}
            format={dateFormat}
            visible={datePickerOpen}
            onClickOutside={() => setDatePickerOpen(false)}
            onChange={(selectedDate) => {
                if (selectedDate) {
                    setDatePickerValue(selectedDate)
                    setValue(selectedDate.format(dateFormat))
                }
                setDatePickerOpen(false)
            }}
            onClose={() => setDatePickerOpen(false)}
            granularity={includeTimeInFilter ? 'minute' : 'day'}
            buttonProps={{ 'data-attr': 'filter-date-picker', fullWidth: true, onClick: () => setDatePickerOpen(true) }}
            showTimeToggle
            onToggleTime={setIncludeTimeInFilter}
        />
    )
}
