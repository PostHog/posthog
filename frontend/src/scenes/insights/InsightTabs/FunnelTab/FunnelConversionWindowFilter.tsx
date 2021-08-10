import { InputNumber, Row, Select, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { pluralize } from 'lib/utils'
import React from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelConversionWindowTimeUnit } from '~/types'

export function FunnelConversionWindowFilter(): JSX.Element {
    const { conversionWindow, conversionWindowValueToShow } = useValues(funnelLogic)
    const { setConversionWindow, loadResults } = useActions(funnelLogic)

    const options = [
        {
            label: pluralize(conversionWindowValueToShow, 'day', 'days', false),
            value: FunnelConversionWindowTimeUnit.Day,
        },
        {
            label: pluralize(conversionWindowValueToShow, 'week', 'weeks', false),
            value: FunnelConversionWindowTimeUnit.Week,
        },
    ]

    return (
        <div className="funnel-options-conversion-window">
            <span className="funnel-options-conversion-window-label">
                Conversion window limit{' '}
                <Tooltip
                    title={
                        <>
                            <b>Recommended!</b> Limit to users who converted within a specific time frame. Users who do
                            not convert in this time frame will be considered as drop-offs.
                        </>
                    }
                >
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            </span>
            <Row className="funnel-options-conversion-window-inputs">
                <InputNumber
                    className="time-value-input"
                    min={1}
                    max={conversionWindow.unit === FunnelConversionWindowTimeUnit.Day ? 365 : 53}
                    defaultValue={14} // days
                    value={conversionWindowValueToShow}
                    onChange={(timeValue) => setConversionWindow({}, Number(timeValue))}
                    onBlur={loadResults}
                    onPressEnter={loadResults}
                />
                <Select
                    className="time-unit-input"
                    defaultValue={FunnelConversionWindowTimeUnit.Day}
                    dropdownMatchSelectWidth={false}
                    value={conversionWindow.unit}
                    onChange={(unit: FunnelConversionWindowTimeUnit) => setConversionWindow({ unit })}
                    onBlur={loadResults}
                >
                    {options.map(({ value, label }) => (
                        <Select.Option value={value} key={value}>
                            {label}
                        </Select.Option>
                    ))}
                </Select>
            </Row>
        </div>
    )
}
