import React from 'react'
import './DurationPicker.scss'
import { SmallTimeUnit } from '~/types'
import { durationPickerLogic, DurationPickerLogicProps } from './durationPickerLogic'
import { useActions, useValues } from 'kea'
import { Input, Select } from 'antd'

interface DurationPickerProps extends DurationPickerLogicProps {
    autoFocus?: boolean
    style?: Partial<React.CSSProperties>
}

export const durationOptions: SmallTimeUnit[] = ['seconds', 'minutes', 'hours']

export function DurationPicker({
    initialValue,
    onChange,
    pageKey,
    autoFocus,
    style,
}: DurationPickerProps): JSX.Element {
    const durationFilterLogicInstance = durationPickerLogic({ initialValue, onChange, pageKey })
    const { setTimeValue, setUnit } = useActions(durationFilterLogicInstance)
    const { unit, timeValue } = useValues(durationFilterLogicInstance)
    return (
        <div className="DurationPicker" style={style}>
            <Input
                className="DurationPicker__time-input"
                type="number"
                value={timeValue ?? undefined}
                placeholder="0"
                min={0}
                autoFocus={autoFocus}
                step={1}
                onChange={(event) => {
                    const newValue = parseFloat(event.target.value)
                    setTimeValue(newValue)
                }}
            />
            <Select
                className="DurationPicker__unit-picker"
                value={unit}
                onChange={(newValue) => {
                    setUnit(newValue as SmallTimeUnit)
                }}
            >
                {durationOptions.map((value) => (
                    <Select.Option key={value} value={value}>
                        {value}
                    </Select.Option>
                ))}
            </Select>
        </div>
    )
}
