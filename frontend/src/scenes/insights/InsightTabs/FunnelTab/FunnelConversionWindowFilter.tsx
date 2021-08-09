import { InputNumber, Row, Select, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { pluralize } from 'lib/utils'
import React from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

export interface FunnelConversionWindow {
    unit?: TimeUnit
    days?: number | undefined
}

export enum TimeUnit {
    Day = 'Day',
    Week = 'Week',
}

export function FunnelConversionWindowFilter(): JSX.Element {
    const { conversionWindow, conversionWindowValueToShow } = useValues(funnelLogic)
    const { setConversionWindow } = useActions(funnelLogic)

    const options = [
        {
            label: pluralize(conversionWindowValueToShow, 'day', 'days', false),
            value: TimeUnit.Day,
        },
        {
            label: pluralize(conversionWindowValueToShow, 'week', 'weeks', false),
            value: TimeUnit.Week,
        },
    ]

    return (
        <Row
            align="middle"
            className="funnel-options-conversion-window"
            style={{ margin: '0.25rem 0', padding: '0.25rem 0' }}
        >
            <span>
                <Tooltip title="Limit to users who converted within a specific number of days.">
                    <InfoCircleOutlined className="info-indicator left" />
                </Tooltip>
                Limit conversion window to{' '}
                <InputNumber
                    className="time-value-input"
                    min={1}
                    max={conversionWindow.unit === TimeUnit.Day ? 365 : 53}
                    defaultValue={14} // days
                    value={conversionWindowValueToShow}
                    onChange={(timeValue) => setConversionWindow({}, Number(timeValue))}
                />
                <Select
                    className="time-unit-input"
                    defaultValue={TimeUnit.Day}
                    dropdownMatchSelectWidth={false}
                    value={conversionWindow.unit}
                    onChange={(unit: TimeUnit) => setConversionWindow({ unit })}
                >
                    {options.map(({ value, label }) => (
                        <Select.Option value={value} key={value}>
                            {label}
                        </Select.Option>
                    ))}
                </Select>
            </span>
        </Row>
    )
}
