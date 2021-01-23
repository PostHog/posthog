import React, { useState } from 'react'
import { useActions } from 'kea'
import { RecordingPropertyFilter } from '~/types'
import { Input, Select } from 'antd'
import { OperatorSelect } from 'lib/components/PropertyFilters/OperatorValueSelect'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'

interface Props {
    filter: RecordingPropertyFilter
    selector: number
}

type TimeUnit = 's' | 'h' | 'm'

const multipliers = { s: 1, m: 60, h: 3600 }

const durationToSeconds = (value: number, unit: TimeUnit): number => value * multipliers[unit]

export function DurationFilter({ filter, selector }: Props): JSX.Element {
    const [unit, setUnit] = useState<TimeUnit>('m')
    const [duration, setDuration] = useState(Math.floor((filter.value as number) / multipliers[unit]))
    const { updateFilter } = useActions(sessionsFiltersLogic)

    return (
        <>
            <OperatorSelect
                operator={filter.operator}
                operators={['gt', 'lt']}
                onChange={(operator) => {
                    updateFilter({ ...filter, operator: operator as 'lt' | 'gt' }, selector)
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
                            updateFilter(
                                {
                                    ...filter,
                                    value: durationToSeconds(duration, newUnit),
                                },
                                selector
                            )
                        }}
                    >
                        <Select.Option value="s">seconds</Select.Option>
                        <Select.Option value="m">minutes</Select.Option>
                        <Select.Option value="h">hours</Select.Option>
                    </Select>
                }
                step={1}
                onChange={(event) => {
                    const value = parseFloat(event.target.value)
                    setDuration(value)
                    updateFilter(
                        {
                            ...filter,
                            value: durationToSeconds(value, unit),
                        },
                        selector
                    )
                }}
            />
        </>
    )
}
