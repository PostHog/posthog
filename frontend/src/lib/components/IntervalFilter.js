import React from 'react'
import { Dropdown } from './Dropdown'
import { disableMinuteFor, disableHourFor } from '../../scenes/trends/trendsLogic'
import { Select } from 'antd'

let intervalMapping = {
    minute: 'Minute',
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    month: 'Monthly',
}

export function IntervalFilter({ filters, setFilters }) {
    const { interval, date_from } = filters
    return (
        <Select
            defaultValue={intervalMapping[interval]}
            value={intervalMapping[interval]}
            onChange={key => {
                const minute_disabled = key === 'minute' && disableMinuteFor[date_from]
                const hour_disabled = key === 'hour' && disableHourFor[date_from]
                if (minute_disabled || hour_disabled) {
                    console.log('minutes disabled')
                    return false
                }

                setFilters({ interval: key })
            }}
            style={{ width: 100 }}
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
