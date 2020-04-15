import React from 'react'
import { Select } from 'antd'

export function SessionFilter(props) {
    let { onChange } = props
    return (
        <Select defaultValue={'avg'} value={'avg'} onChange={onChange} dropdownMatchSelectWidth={false}>
            <Select.Option value="avg">Average Session Length</Select.Option>
            <Select.Option value="dist">Distribution of Session Lengths</Select.Option>
        </Select>
    )
}
