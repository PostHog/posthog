import React from 'react'
import { Select } from 'antd'

const options = {
    $pageview: 'Pageview (Web)',
    $screen: 'Screen (Mobile)',
    $autocapture: 'Autocaptured Events',
    custom_event: 'Custom Events',
}

export function PathSelect(props) {
    return (
        <Select
            value={props.value || '$pageview'}
            bordered={false}
            defaultValue="$pageview"
            dropdownMatchSelectWidth={false}
            {...props}
        >
            {Object.entries(options).map(([value, name], index) => {
                return (
                    <Select.Option key={index} value={value}>
                        {name}
                    </Select.Option>
                )
            })}
        </Select>
    )
}
