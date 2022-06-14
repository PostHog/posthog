import { dayjs } from 'lib/dayjs'
import React, { useEffect, useState } from 'react'
import { isOperatorDate } from 'lib/utils'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { PropertyOperator } from '~/types'
import { PropertyValueProps } from 'lib/components/PropertyFilters/components/PropertyValue'
import { DatePicker } from 'lib/components/DatePicker'

const dayJSMightParse = (
    candidateDateTimeValue: string | number | (string | number)[] | null | undefined
): candidateDateTimeValue is string | number | undefined => ['string', 'number'].includes(typeof candidateDateTimeValue)

const narrowToString = (
    candidateDateTimeValue: string | number | (string | number)[] | null | undefined
): candidateDateTimeValue is string | null | undefined =>
    candidateDateTimeValue == undefined || typeof candidateDateTimeValue === 'string'

interface PropertyFilterDatePickerProps {
    autoFocus: boolean
    operator: PropertyOperator
    setValue: (newValue: PropertyValueProps['value']) => void
    value: string | number | (string | number)[] | null | undefined
    style: Partial<React.CSSProperties>
}

const dateAndTimeFormat = 'YYYY-MM-DD HH:mm:ss'
const onlyDateFormat = 'YYYY-MM-DD'

export function PropertyFilterDatePicker({
    autoFocus,
    operator,
    setValue,
    value,
    style,
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
        <DatePicker
            style={style}
            autoFocus={autoFocus}
            open={datePickerOpen}
            inputReadOnly={false}
            className={'filter-date-picker'}
            dropdownClassName={'filter-date-picker-dropdown'}
            format={dateFormat}
            showTime={includeTimeInFilter}
            showNow={false}
            showToday={false}
            value={datePickerValue}
            onFocus={() => setDatePickerOpen(true)}
            onBlur={() => setDatePickerOpen(false)}
            onOk={(selectedDate) => {
                setDatePickerValue(selectedDate)
                setValue(selectedDate.format(dateFormat))
                setDatePickerOpen(false)
            }}
            onSelect={(selectedDate) => {
                // the OK button is only shown when the time is visible
                // https://github.com/ant-design/ant-design/issues/22966
                // if time picker is visible wait for OK, otherwise select the date
                if (includeTimeInFilter) {
                    return // we wait for a click on OK
                }
                setDatePickerValue(selectedDate)
                setValue(selectedDate.format(dateFormat))
                setDatePickerOpen(false)
            }}
            getPopupContainer={(trigger: Element | null) => {
                const container = trigger?.parentElement?.parentElement?.parentElement
                return container ?? document.body
            }}
            renderExtraFooter={() => (
                <LemonSwitch
                    label="Include time?"
                    checked={includeTimeInFilter}
                    onChange={(active) => {
                        setIncludeTimeInFilter(active)
                    }}
                />
            )}
        />
    )
}
