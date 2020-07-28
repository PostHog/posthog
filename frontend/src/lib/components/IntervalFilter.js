import React from 'react'
import { disableMinuteFor, disableHourFor } from 'scenes/trends/trendsLogic'
import { Select } from 'antd'

let intervalMapping = {
    minute: 'Minute',
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    month: 'Monthly',
}

export function IntervalFilter({ filters, setFilters, disabled = false }) {
    const { interval } = filters
    let date_from
    return (
        <Select
            bordered={false}
            disabled={disabled}
            defaultValue={intervalMapping[interval]}
            value={intervalMapping[interval]}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                switch (key) {
                    case 'minute':
                        date_from = 'dStart'
                        break
                    case 'hour':
                        date_from = 'dStart'
                        break
                    case 'week':
                        date_from = '-30d'
                        break
                    case 'month':
                        date_from = '-90d'
                        break
                    default:
                        date_from = undefined
                        break
                }
                const minute_disabled = key === 'minute' && disableMinuteFor[date_from]
                const hour_disabled = key === 'hour' && disableHourFor[date_from]
                if (minute_disabled || hour_disabled) {
                    return false
                }

                if (date_from) {
                    setFilters({ interval: key, date_from: date_from })
                } else {
                    setFilters({ interval: key })
                }
            }}
            data-attr="interval-filter"
        >
            {Object.entries(intervalMapping).map(([key, value]) => {
                return (
                    <Select.Option
                        key={key}
                        value={key}
                        disabled={(key === 'minute' || key === 'hour') && !!filters.session}
                    >
                        {value}
                    </Select.Option>
                )
            })}
        </Select>
    )
}
