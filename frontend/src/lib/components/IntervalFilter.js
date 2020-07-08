import React from 'react'
import { disableMinuteFor, disableHourFor } from '../../scenes/trends/trendsLogic'
import { Select } from 'antd'

let intervalMapping = {
    minute: 'Minute',
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    month: 'Monthly',
}

export function IntervalFilter({ filters, setFilters, disabled = false }) {
    const { interval, date_from } = filters
    return (
        <Select
            bordered={false}
            disabled={disabled}
            defaultValue={intervalMapping[interval]}
            value={intervalMapping[interval]}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                const minute_disabled = key === 'minute' && disableMinuteFor[date_from]
                const hour_disabled = key === 'hour' && disableHourFor[date_from]
                if (minute_disabled || hour_disabled) {
                    return false
                }
                setFilters({ interval: key })
            }}
            data-attr="interval-filter"
        >
            {Object.entries(intervalMapping).map(([key, value]) => {
                return (
                    <Select.Option key={key} value={key}>
                        {value}
                    </Select.Option>
                )
            })}
        </Select>
    )
}
