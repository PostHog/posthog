import generatePicker from 'antd/lib/date-picker/generatePicker'
import { dayjs, now } from 'lib/dayjs'
import dayjsGenerateConfig from 'rc-picker/es/generate/dayjs'
import React, { useEffect, useState } from 'react'
import { dateMapping, isOperatorDate } from 'lib/utils'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { Select } from 'antd'
import { PropertyOperator } from '~/types'
import { PropertyValueProps } from 'lib/components/PropertyFilters/components/PropertyValue'

export const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)

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
    const [datePickerStartingValue] = useState(dayJSMightParse(value) ? dayjs(value) : null)
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
            value={datePickerStartingValue}
            onFocus={() => setDatePickerOpen(true)}
            onBlur={() => setDatePickerOpen(false)}
            onOk={(selectedDate) => {
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
                setValue(selectedDate.format(dateFormat))
                setDatePickerOpen(false)
            }}
            getPopupContainer={(trigger: Element | null) => {
                const container = trigger?.parentElement?.parentElement?.parentElement
                return container ?? document.body
            }}
            renderExtraFooter={() => (
                <>
                    <LemonSwitch
                        label={<>Include time?</>}
                        checked={includeTimeInFilter}
                        loading={false}
                        data-attr="share-dashboard-switch"
                        onChange={(active) => {
                            setIncludeTimeInFilter(active)
                        }}
                    />
                    <span>Quick choices: </span>{' '}
                    <Select
                        bordered={true}
                        style={{ width: '100%', paddingBottom: '1rem' }}
                        onSelect={(selectedRelativeRange) => {
                            const matchedMapping = dateMapping[String(selectedRelativeRange)]
                            const formattedForDateFilter =
                                matchedMapping?.getFormattedDate && matchedMapping?.getFormattedDate(now(), dateFormat)
                            setValue(formattedForDateFilter?.split(' - ')[0])
                        }}
                        placeholder={'e.g. 7 days ago'}
                    >
                        {[
                            ...Object.entries(dateMapping).map(([key, { inactive }]) => {
                                if (key === 'Custom' || key == 'All time' || inactive) {
                                    return null
                                }

                                return (
                                    <Select.Option key={key} value={key}>
                                        {key.startsWith('Last') ? key.replace('Last ', '') + ' ago' : key}
                                    </Select.Option>
                                )
                            }),
                        ]}
                    </Select>
                </>
            )}
        />
    )
}
