import React from 'react'
import { Select } from 'antd'

interface SessionFilterProps {
    onChange: (value: string) => void
    value: string | undefined
}

export function SessionFilter({ onChange, value }: SessionFilterProps): JSX.Element {
    return (
        <Select
            style={{ maxWidth: '100%' }}
            defaultValue={value}
            value={value}
            dropdownMatchSelectWidth={false}
            onChange={onChange}
            data-attr="sessions-filter"
        >
            <Select.Option value="avg">Average Session Length</Select.Option>
            <Select.Option value="dist" data-attr="sessions-filter-distribution">
                Distribution of Session Lengths
            </Select.Option>
        </Select>
    )
}
