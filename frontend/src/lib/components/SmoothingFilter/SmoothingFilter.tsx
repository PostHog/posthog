import React from 'react'
import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { smoothingOptions } from './smoothings'
import { useActions, useValues } from 'kea'
import { smoothingFilterLogic } from './smoothingFilterLogic'

export function SmoothingFilter(): JSX.Element | null {
    const { filters, smoothing } = useValues(smoothingFilterLogic)
    const { setSmoothing } = useActions(smoothingFilterLogic)

    if (filters.interval === null || filters.interval === undefined) {
        return null
    }

    // Put a little icon next to the selected item
    const options = smoothingOptions[filters.interval].map(({ value, label }) => ({
        value,
        label:
            value === smoothing ? (
                <>
                    <FundOutlined /> {label}
                </>
            ) : (
                label
            ),
    }))

    return options.length ? (
        <Select
            key={filters.interval}
            bordered={false}
            value={smoothing || undefined}
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
