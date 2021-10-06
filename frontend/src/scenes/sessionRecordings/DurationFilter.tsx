import React, { useState } from 'react'
import { PropertyOperator, RecordingDurationFilter } from '~/types'
import { Button, Input, Row, Select, Space } from 'antd'
import { OperatorSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { Popup } from 'lib/components/Popup/Popup'

type TimeUnit = 'seconds' | 'hours' | 'minutes'

const multipliers = { seconds: 1, minutes: 60, hours: 3600 }

const durationToSeconds = (value: number, unit: TimeUnit): number => value * multipliers[unit]

interface Props {
    filterValue: RecordingDurationFilter
    onChange: (value: RecordingDurationFilter) => void
}

export function DurationFilter({ filterValue, onChange }: Props): JSX.Element {
    const [unit, setUnit] = useState<TimeUnit>('minutes')
    const [duration, setDuration] = useState(Math.floor((filterValue.value as number) / multipliers[unit]))
    const [open, setOpen] = useState(false)

    const updateOperator = (operator: PropertyOperator): void => {
        onChange({
            ...filterValue,
            operator: operator,
        })
    }

    const updateValue = (newValue: number, newUnit: TimeUnit): void => {
        onChange({
            ...filterValue,
            value: durationToSeconds(newValue, newUnit),
        })
    }

    const getDurationString = (): string => {
        let durationString = ''
        if (filterValue.operator === PropertyOperator.GreaterThan) {
            durationString += '> '
        } else {
            durationString += '< '
        }
        durationString += duration
        if (duration === 1) {
            durationString += ' ' + unit.slice(0, -1)
        } else {
            durationString += ' ' + unit
        }
        return durationString
    }

    return (
        <Popup
            visible={open}
            placement={'bottom-end'}
            fallbackPlacements={['bottom-start']}
            onClickOutside={() => setOpen(false)}
            overlay={
                <Row>
                    <Space>
                        <OperatorSelect
                            operator={filterValue.operator}
                            operators={[PropertyOperator.GreaterThan, PropertyOperator.LessThan]}
                            onChange={(operator) => {
                                updateOperator(operator)
                            }}
                        />

                        <Input
                            type="number"
                            value={duration}
                            placeholder="0"
                            min={0}
                            autoFocus
                            addonAfter={
                                <Select
                                    showSearch={false}
                                    value={unit}
                                    onChange={(newUnit: TimeUnit) => {
                                        setUnit(newUnit)
                                        updateValue(duration, newUnit)
                                    }}
                                >
                                    <Select.Option value="seconds">Seconds</Select.Option>
                                    <Select.Option value="minutes">Minutes</Select.Option>
                                    <Select.Option value="hours">Hours</Select.Option>
                                </Select>
                            }
                            step={1}
                            onChange={(event) => {
                                const newValue = parseFloat(event.target.value)
                                setDuration(newValue)
                                updateValue(newValue, unit)
                            }}
                        />
                    </Space>
                </Row>
            }
        >
            <Button
                onClick={() => {
                    setOpen(true)
                }}
            >
                {getDurationString()}
            </Button>
        </Popup>
    )
}
