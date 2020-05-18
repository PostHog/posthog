import React from 'react'
import { Select } from 'antd'

const options = {
    $pageview: 'Pageview (Web)',
    $screen: 'Screen (Mobile)',
    $autocapture: 'Autocaptured Events',
    custom_event: 'All Other Events',
}

export function PathSelect(props) {
    return (
        <Select bordered={false} defaultValue="$pageview" dropdownMatchSelectWidth={false} {...props}>
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
