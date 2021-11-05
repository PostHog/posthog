import React from 'react'
import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { smoothingOptions } from './smoothings'
import { useActions, useValues } from 'kea'
import { smoothingFilterLogic } from './smoothingFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function SmoothingFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const smoothingFilterLogicWithProps = smoothingFilterLogic(insightProps)
    const {
        filters: { interval, smoothing_intervals },
    } = useValues(smoothingFilterLogicWithProps)
    const { setSmoothing } = useActions(smoothingFilterLogicWithProps)

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
