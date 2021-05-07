import React from 'react'
import { Select } from 'antd'
import { intervalFilterLogic } from './intervalFilterLogic'
import { useValues, useActions } from 'kea'
import { ViewType } from 'scenes/insights/insightLogic'
import { disableHourFor, disableMinuteFor } from 'lib/utils'

const intervalMapping = {
    minute: 'Minute',
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    month: 'Monthly',
}

interface InvertalFilterProps {
    view: ViewType
    disabled?: boolean
}

export function IntervalFilter({ view, disabled }: InvertalFilterProps): JSX.Element {
    const interval: 'minute' | 'hour' | 'day' | 'week' | 'month' = useValues(intervalFilterLogic).interval
    const { setIntervalFilter, setDateFrom } = useActions(intervalFilterLogic)
    return (
        <Select
            bordered={false}
            disabled={disabled}
            defaultValue={intervalMapping[interval] || intervalMapping['day']}
            value={intervalMapping[interval]}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                let newDateFrom

                switch (key) {
                    case 'minute':
                        newDateFrom = 'dStart'
                        break
                    case 'hour':
                        newDateFrom = 'dStart'
                        break
                    case 'week':
                        newDateFrom = '-30d'
                        break
                    case 'month':
                        newDateFrom = '-90d'
                        break
                    default:
                        newDateFrom = undefined
                        break
                }

                const minute_disabled = key === 'minute' && newDateFrom && disableMinuteFor[newDateFrom]
                const hour_disabled = key === 'hour' && newDateFrom && disableHourFor[newDateFrom]
                if (minute_disabled || hour_disabled) {
                    return false
                }

                if (newDateFrom) {
                    setDateFrom(newDateFrom)
                }

                setIntervalFilter(key)
            }}
            data-attr="interval-filter"
        >
            {Object.entries(intervalMapping).map(([key, value]) => (
                <Select.Option
                    key={key}
                    value={key}
                    disabled={(key === 'minute' || key === 'hour') && view === ViewType.SESSIONS}
                >
                    {value}
                </Select.Option>
            ))}
        </Select>
    )
}
