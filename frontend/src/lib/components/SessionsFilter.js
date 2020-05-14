import React from 'react'
import { Select } from 'antd'

export function SessionFilter(props) {
    let { onChange, value } = props
    return (
        <Select
            style={{ maxWidth: '100%' }}
            defaultValue={value}
            value={value}
            dropdownMatchSelectWidth={false}
            onChange={onChange}
        >
            <Select.Option value="avg">Average Session Length</Select.Option>
            <Select.Option value="dist">Distribution of Session Lengths</Select.Option>
        </Select>
    )
}
