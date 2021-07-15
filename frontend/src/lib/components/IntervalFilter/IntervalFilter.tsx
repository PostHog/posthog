import React from 'react'
import { Select } from 'antd'
import { intervalFilterLogic } from './intervalFilterLogic'
import { useValues, useActions } from 'kea'
import { disableHourFor, disableMinuteFor } from 'lib/utils'
import { CalendarOutlined } from '@ant-design/icons'
import { defaultInterval, IntervalKeyType, intervals } from 'lib/components/IntervalFilter/intervals'
import { ViewType } from '~/types'

interface InvertalFilterProps {
    view: ViewType
    disabled?: boolean
}

export function IntervalFilter({ view, disabled }: InvertalFilterProps): JSX.Element {
    const { interval } = useValues(intervalFilterLogic)
    const { setIntervalFilter, setDateFrom } = useActions(intervalFilterLogic)
    const options = Object.entries(intervals).map(([key, { label }]) => ({
        key,
        value: key,
        label:
            key === interval ? (
                <>
                    <CalendarOutlined /> {label}
                </>
            ) : (
                label
            ),
        disabled: (key === 'minute' || key === 'hour') && view === ViewType.SESSIONS,
    }))
    return (
        <Select
            bordered={false}
            disabled={disabled}
            defaultValue={interval || 'day'}
            value={interval || undefined}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                const { newDateFrom } = intervals[key as IntervalKeyType] || defaultInterval
                const minuteDisabled = key === 'minute' && newDateFrom && disableMinuteFor[newDateFrom]
                const hourDisabled = key === 'hour' && newDateFrom && disableHourFor[newDateFrom]
                if (minuteDisabled || hourDisabled) {
                    return false
                }

                if (newDateFrom) {
                    setDateFrom(newDateFrom)
                }

                setIntervalFilter(key)
            }}
            data-attr="interval-filter"
            options={options}
        />
    )
}
