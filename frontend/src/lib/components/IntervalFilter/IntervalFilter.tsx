import React from 'react'
import { Select } from 'antd'
import { intervalFilterLogic } from './intervalFilterLogic'
import { useValues, useActions } from 'kea'
import { CalendarOutlined } from '@ant-design/icons'
import { intervals } from 'lib/components/IntervalFilter/intervals'
import { InsightType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

interface InvertalFilterProps {
    view: InsightType
    disabled?: boolean
}

export function IntervalFilter({ view, disabled }: InvertalFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { interval } = useValues(intervalFilterLogic(insightProps))
    const { setInterval } = useActions(intervalFilterLogic(insightProps))
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
        disabled: key === 'hour' && view === InsightType.SESSIONS,
    }))
    return (
        <Select
            bordered
            disabled={disabled}
            defaultValue={interval || 'day'}
            value={interval || undefined}
            dropdownMatchSelectWidth={false}
            onChange={setInterval}
            data-attr="interval-filter"
            options={options}
        />
    )
}
