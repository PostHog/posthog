import { useEffect, useState } from 'react'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { Duration, SmallTimeUnit } from '~/types'

interface DurationPickerProps {
    onChange: (value_seconds: number) => void
    value?: number
    autoFocus?: boolean
}

export const durationOptions: SmallTimeUnit[] = ['seconds', 'minutes', 'hours']

const TIME_MULTIPLIERS: Record<SmallTimeUnit, number> = { seconds: 1, minutes: 60, hours: 3600 }

export const convertSecondsToDuration = (seconds: number): Duration => {
    const orderOfUnitsToTest: SmallTimeUnit[] = ['hours', 'minutes']
    for (const unit of orderOfUnitsToTest) {
        if (seconds / TIME_MULTIPLIERS[unit] >= 1 && seconds % TIME_MULTIPLIERS[unit] === 0) {
            return {
                timeValue: seconds / TIME_MULTIPLIERS[unit],
                unit: unit,
            }
        }
    }
    return {
        timeValue: seconds,
        unit: 'seconds',
    }
}

export function DurationPicker({ value, onChange, autoFocus }: DurationPickerProps): JSX.Element {
    const duration = convertSecondsToDuration(value || 0)

    const [localTimeValue, setLocalTimeValue] = useState<number | undefined>(duration.timeValue)
    const [unit, setUnit] = useState<SmallTimeUnit>(duration.unit)

    useEffect(() => {
        // Update the local state when the value changes
        setLocalTimeValue(convertSecondsToDuration(value || 0).timeValue)
        setUnit(convertSecondsToDuration(value || 0).unit)
    }, [value])

    const _onChange = ({ newTimeValue, newUnit }: { newTimeValue?: number; newUnit: SmallTimeUnit }): void => {
        setLocalTimeValue(newTimeValue)
        setUnit(newUnit)

        if (newTimeValue !== undefined) {
            const seconds = newTimeValue * TIME_MULTIPLIERS[newUnit]
            // We want to allow clearing the input so we only trigger the change if it was actually set
            onChange(seconds)
        }
    }

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="number"
                value={localTimeValue}
                placeholder="0"
                min={0}
                autoFocus={autoFocus}
                step={1}
                onChange={(val) => _onChange({ newTimeValue: val, newUnit: unit })}
            />
            <LemonSelect
                value={unit}
                onChange={(newValue) => _onChange({ newUnit: newValue as SmallTimeUnit, newTimeValue: localTimeValue })}
                options={durationOptions.map((value) => ({ value, label: value }))}
            />
        </div>
    )
}
