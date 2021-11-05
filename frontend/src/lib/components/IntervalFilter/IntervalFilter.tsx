import React from 'react'
import { Select } from 'antd'
import { useValues, useActions } from 'kea'
import { disableHourFor, disableMinuteFor } from 'lib/utils'
import { CalendarOutlined } from '@ant-design/icons'
import { defaultInterval, IntervalKeyType, intervals } from 'lib/components/IntervalFilter/intervals'
import { ViewType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

export function IntervalFilter(): JSX.Element {
    const { filters } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)
    const options = Object.entries(intervals).map(([key, { label }]) => ({
        key,
        value: key,
        label:
            key === filters.interval ? (
                <>
                    <CalendarOutlined /> {label}
                </>
            ) : (
                label
            ),
        disabled: (key === 'minute' || key === 'hour') && filters.insight === ViewType.SESSIONS,
    }))
    return (
        <Select
            bordered={false}
            value={filters.interval || 'day'}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                const { newDateFrom } = intervals[key as IntervalKeyType] || defaultInterval
                const minuteDisabled = key === 'minute' && newDateFrom && disableMinuteFor[newDateFrom]
                const hourDisabled = key === 'hour' && newDateFrom && disableHourFor[newDateFrom]
                if (minuteDisabled || hourDisabled) {
                    return false
                }

                setFilters({ ...filters, interval: key, ...(newDateFrom ? { date_from: newDateFrom } : {}) })
            }}
            data-attr="interval-filter"
            options={options}
        />
    )
}
