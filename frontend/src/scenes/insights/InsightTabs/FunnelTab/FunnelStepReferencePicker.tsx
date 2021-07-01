import React from 'react'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { PercentageOutlined } from '@ant-design/icons'

export enum FunnelStepReference {
    total = 'total',
    previous = 'previous',
}

export default function FunnelStepReferencePicker(): JSX.Element {
    const { stepReference } = useValues(funnelLogic)
    const { setStepReference } = useActions(funnelLogic)
    const options = [
        {
            value: FunnelStepReference.total,
            label: (
                <>
                    <PercentageOutlined /> Absolute values
                </>
            ),
        },
        {
            value: FunnelStepReference.previous,
            label: (
                <>
                    <PercentageOutlined /> Relative to previous step
                </>
            ),
        },
    ]
    return (
        <Select
            defaultValue={FunnelStepReference.total}
            value={stepReference || FunnelStepReference.total}
            onChange={setStepReference}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-step-reference-selector"
            options={options}
        />
    )
}
