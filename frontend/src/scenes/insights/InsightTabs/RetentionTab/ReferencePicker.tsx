import React from 'react'
import { Select } from 'antd'
import { PercentageOutlined } from '@ant-design/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useActions, useValues } from 'kea'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'

const options = {
    total: {
        value: 'total',
        icon: <PercentageOutlined />,
        label: 'Overall cohort',
        description: 'Display retention values relative to initial cohort size',
    },
    previous: {
        value: 'previous',
        icon: <PercentageOutlined />,
        label: 'Relative to previous period',
        description: `
            Display retention values relative to previous retention period. When
            displayed as a line graph, this is what is sometimes called a J-Curve or
            smile graph, and is intended to identify how quickly the dropoff of
            users is tending towards zero
        `,
    },
} as const

export function ReferencePicker(): JSX.Element {
    /*
        Reference picker specifies how retention values should be displayed,
        options and description found in `enum Reference`
    */
    const { insightProps } = useValues(insightLogic)
    const { retentionReference } = useValues(retentionTableLogic(insightProps))
    const { setRetentionReference } = useActions(retentionTableLogic(insightProps))

    return (
        <Select
            value={retentionReference}
            onChange={setRetentionReference}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="reference-selector"
            optionLabelProp="label"
        >
            {Object.values(options).map((option) => (
                <Select.Option
                    key={option.value}
                    value={option.value}
                    label={
                        <>
                            {option.icon} {option.label}
                        </>
                    }
                >
                    {option.label}
                </Select.Option>
            ))}
        </Select>
    )
}
