import React from 'react'
import { disableMinuteFor, disableHourFor } from 'scenes/insights/trendsLogic'
import { Select } from 'antd'
import { intervalFilterLogic } from './intervalFilterLogic'
import { useValues, useActions } from 'kea'
import { ViewType } from 'scenes/insights/insightLogic'

let intervalMapping = {
    minute: 'Minute',
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    month: 'Monthly',
}

export function IntervalFilter({ view, disabled = false }) {
    let date_from

    const { interval } = useValues(intervalFilterLogic)
    const { setIntervalFilter, setDateFrom } = useActions(intervalFilterLogic)
    return (
        <Select
            bordered={false}
            disabled={disabled}
            defaultValue={intervalMapping[interval] || intervalMapping['day']}
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
                    setDateFrom(date_from)
                }

                setIntervalFilter(key)
            }}
            data-attr="interval-filter"
        >
            {Object.entries(intervalMapping).map(([key, value]) => {
                return (
                    <Select.Option
                        key={key}
                        value={key}
                        disabled={(key === 'minute' || key === 'hour') && view === ViewType.SESSIONS}
                    >
                        {value}
                    </Select.Option>
                )
            })}
        </Select>
    )
}
