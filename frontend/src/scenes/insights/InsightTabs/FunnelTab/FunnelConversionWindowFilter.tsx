import { InputNumber, Row, Select } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { pluralize } from 'lib/utils'
import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelConversionWindow, FunnelConversionWindowTimeUnit } from '~/types'
import { Tooltip } from 'lib/components/Tooltip'

const TIME_INTERVAL_BOUNDS: Record<FunnelConversionWindowTimeUnit, number[]> = {
    [FunnelConversionWindowTimeUnit.Minute]: [1, 1440],
    [FunnelConversionWindowTimeUnit.Hour]: [1, 24],
    [FunnelConversionWindowTimeUnit.Day]: [1, 365],
    [FunnelConversionWindowTimeUnit.Week]: [1, 53],
    [FunnelConversionWindowTimeUnit.Month]: [1, 12],
}

export function FunnelConversionWindowFilter(): JSX.Element {
    const { conversionWindow } = useValues(funnelLogic)
    const { setConversionWindow } = useActions(funnelLogic)
    const [localConversionWindow, setLocalConversionWindow] = useState<FunnelConversionWindow>(conversionWindow)

    const options = Object.keys(TIME_INTERVAL_BOUNDS).map((unit) => ({
        label: pluralize(conversionWindow.funnel_window_interval ?? 7, unit, `${unit}s`, false),
        value: unit,
    }))
    const intervalBounds =
        TIME_INTERVAL_BOUNDS[conversionWindow.funnel_window_interval_unit ?? FunnelConversionWindowTimeUnit.Day]

    const onChange = (): void => {
        if (
            localConversionWindow.funnel_window_interval !== conversionWindow.funnel_window_interval ||
            localConversionWindow.funnel_window_interval_unit !== conversionWindow.funnel_window_interval_unit
        ) {
            setConversionWindow(localConversionWindow)
        }
    }

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
                    min={intervalBounds[0]}
                    max={intervalBounds[1]}
                    defaultValue={14}
                    value={localConversionWindow.funnel_window_interval}
                    onChange={(funnel_window_interval) =>
                        setLocalConversionWindow((state) => ({
                            ...state,
                            funnel_window_interval: Number(funnel_window_interval),
                        }))
                    }
                    onBlur={onChange}
                    onPressEnter={onChange}
                />
                <Select
                    className="time-unit-input"
                    defaultValue={FunnelConversionWindowTimeUnit.Day}
                    dropdownMatchSelectWidth={false}
                    value={localConversionWindow.funnel_window_interval_unit}
                    onChange={(funnel_window_interval_unit: FunnelConversionWindowTimeUnit) =>
                        setLocalConversionWindow((state) => ({ ...state, funnel_window_interval_unit }))
                    }
                    onBlur={onChange}
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
