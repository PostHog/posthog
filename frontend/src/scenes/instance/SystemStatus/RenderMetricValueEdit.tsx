import { Checkbox, Input } from 'antd'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
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
        return (
            <>
                <Checkbox defaultChecked={!!value} onChange={(e) => onValueChanged(key, e.target.checked)} />
                <LemonTag style={{ marginLeft: 4 }} type={value ? 'success' : 'danger'}>
                    {value ? 'Yes' : 'No'}
                </LemonTag>
            </>
        )
    }

    return (
        <Input
            defaultValue={value as string | number | ReadonlyArray<string>}
            type={value_type === 'int' ? 'number' : 'text'}
            onBlur={(e) => onValueChanged(key, e.target.value)}
        />
    )
}
