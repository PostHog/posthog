import React from 'react'
import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { smoothingOptions } from './smoothings'
import { useActions, useValues } from 'kea'
import { smoothingFilterLogic } from './smoothingFilterLogic'

export function SmoothingFilter(): JSX.Element | null {
    const {
        filters: { interval, smoothing_intervals },
    } = useValues(smoothingFilterLogic)
    const { setSmoothing } = useActions(smoothingFilterLogic)

    if (interval === null || interval === undefined) {
        return null
    }

    // Put a little icon next to the selected item
    const options = smoothingOptions[interval].map(({ value, label }) => ({
        value,
        label:
            value === smoothing_intervals ? (
                <>
                    <FundOutlined /> {label}
                </>
            ) : (
                label
            ),
    }))

    return options.length ? (
        <Select
            key={interval}
            bordered={false}
            value={smoothing_intervals || undefined}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                setSmoothing(key)
            }}
            data-attr="smoothing-filter"
            options={options}
        />
    ) : (
        <></>
    )
}
