import React from 'react'
import { Select } from 'antd'

export function SessionFilter(props) {
    let { onChange } = props
    return (
        <Select defaultValue={'avg'} dropdownMatchSelectWidth={false} onChange={onChange}>
            <Select.Option value="avg">Average Session Length</Select.Option>
            <Select.Option value="dist">Distribution of Session Lengths</Select.Option>
        </Select>
    )
}
