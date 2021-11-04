import React from 'react'
import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { smoothingOptions } from './smoothings'
import { useActions, useValues } from 'kea'
import { smoothingFilterLogic } from './smoothingFilterLogic'

export function SmoothingFilter(): JSX.Element | null {
    const { interval, smoothing } = useValues(smoothingFilterLogic)
    const { setSmoothingFilter } = useActions(smoothingFilterLogic)

    if (interval === null) {
        return null
    }

    // Put a little icon next to the selected item
    const options = smoothingOptions[interval].map(({ value, label }) => ({
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
            key={interval}
            bordered={false}
            value={smoothing || undefined}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                setSmoothingFilter(key)
            }}
            data-attr="smoothing-filter"
            options={options}
        />
    ) : (
        <></>
    )
}
