import { Col, InputNumber, Row, Select, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { pluralize } from 'lib/utils'
import React from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelConversionWindowTimeUnit } from '~/types'

const TIME_INTERVAL_BOUNDS: Record<FunnelConversionWindowTimeUnit, number[]> = {
    [FunnelConversionWindowTimeUnit.Minute]: [1, 1440],
    [FunnelConversionWindowTimeUnit.Hour]: [1, 24],
    [FunnelConversionWindowTimeUnit.Day]: [1, 365],
    [FunnelConversionWindowTimeUnit.Week]: [1, 53],
    [FunnelConversionWindowTimeUnit.Month]: [1, 12],
}

export function FunnelConversionWindowFilter(): JSX.Element {
    const { conversionWindow } = useValues(funnelLogic)
    const { setConversionWindow, loadResults } = useActions(funnelLogic)

    const options = Object.keys(TIME_INTERVAL_BOUNDS).map((unit) => ({
        label: pluralize(conversionWindow.funnel_window_interval, unit, `${unit}s`, false),
        value: unit,
    }))
    const intervalBounds = TIME_INTERVAL_BOUNDS[conversionWindow.funnel_window_interval_unit]

    return (
        <div style={{ paddingBottom: '1rem' }}>
            <h4 className="secondary">
                Conversion Window
                <Tooltip title="Only conversions within this timeframe of performing the initial step are counted.">
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            </h4>
            <Row gutter={8} align="middle">
                <Col>
                    <InputNumber
                        className="time-value-input"
                        min={intervalBounds[0]}
                        max={intervalBounds[1]}
                        defaultValue={14}
                        value={conversionWindow.funnel_window_interval}
                        onChange={(funnel_window_interval) => {
                            setConversionWindow({ funnel_window_interval: Number(funnel_window_interval) })
                            loadResults()
                        }}
                        onPressEnter={loadResults}
                    />
                </Col>
                <Col>
                    <Select
                        className="time-unit-input"
                        defaultValue={FunnelConversionWindowTimeUnit.Day}
                        dropdownMatchSelectWidth={false}
                        value={conversionWindow.funnel_window_interval_unit}
                        onChange={(funnel_window_interval_unit: FunnelConversionWindowTimeUnit) => {
                            setConversionWindow({ funnel_window_interval_unit })
                            loadResults()
                        }}
                    >
                        {options.map(({ value, label }) => (
                            <Select.Option value={value} key={value}>
                                {label}
                            </Select.Option>
                        ))}
                    </Select>
                </Col>
            </Row>
        </div>
    )
}
