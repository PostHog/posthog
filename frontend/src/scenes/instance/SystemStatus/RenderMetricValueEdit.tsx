import { Input, Switch } from 'antd'
import React from 'react'
import { MetricValueInterface } from './RenderMetricValue'

interface MetricValueEditInterface extends MetricValueInterface {
    onValueChanged: (key: string, value: any) => void
}

export function RenderMetricValueEdit({
    key,
    value,
    value_type,
    onValueChanged,
}: MetricValueEditInterface): JSX.Element | string {
    if (value_type === 'bool') {
        return <Switch defaultChecked={value} onChange={(val) => onValueChanged(key, val)} />
    }

    return (
        <Input
            defaultValue={value}
            type={value_type === 'int' ? 'number' : 'text'}
            onBlur={(e) => onValueChanged(key, e.target.value)}
        />
    )
}
