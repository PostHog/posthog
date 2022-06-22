import React from 'react'
import './DurationPicker.scss'
import { TimeUnit } from '~/types'
import { durationPickerLogic } from './durationPickerLogic'
import { useActions, useValues } from 'kea'
import { Input, Select } from 'antd'
import { capitalizeFirstLetter } from 'lib/utils'

interface Props {
    initialValue: number
    onChange: (value: number) => void
    key: string
    autoFocus: boolean
    style: Partial<React.CSSProperties>
}

export const durationOptions: TimeUnit[] = ['seconds', 'minutes', 'hours']

export function DurationPicker({ initialValue, onChange, key, autoFocus, style }: Props): JSX.Element {
    const durationFilterLogicInstance = durationPickerLogic({ initialValue, onChange, key })
    const { setTimeValue, setUnit } = useActions(durationFilterLogicInstance)
    const { unit, timeValue } = useValues(durationFilterLogicInstance)
    return (
        <div className="DurationPicker" style={style}>
            <Input
                className="DurationPicker__time-input"
                type="number"
                value={timeValue}
                placeholder="0"
                min={0}
                autoFocus={autoFocus}
                step={1}
                onChange={(event) => {
                    console.log(event.target.value)
                    const newValue = parseFloat(event.target.value)
                    setTimeValue(newValue)
                }}
            />
            <Select
                className="DurationPicker__unit-picker"
                value={unit}
                onChange={(newValue) => {
                    setUnit(newValue as TimeUnit)
                }}
            >
                {durationOptions.map((value) => (
                    <Select.Option key={value} value={value}>
                        {capitalizeFirstLetter(value)}
                    </Select.Option>
                ))}
            </Select>
        </div>
    )
}
