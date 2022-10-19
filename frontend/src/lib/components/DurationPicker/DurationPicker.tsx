import { useEffect, useState } from 'react'
import { Duration, SmallTimeUnit } from '~/types'
import { LemonSelect, LemonInput } from '@posthog/lemon-ui'

interface DurationPickerProps {
    onChange: (value_seconds: number) => void
    initialValue?: number
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

export function DurationPicker({ initialValue, onChange, autoFocus }: DurationPickerProps): JSX.Element {
    const [timeValue, setTimeValue] = useState(convertSecondsToDuration(initialValue || 0).timeValue)
    const [unit, setUnit] = useState(convertSecondsToDuration(initialValue || 0).unit)

    useEffect(() => {
        const timeValueToUse = timeValue || 0
        const unitToUse = unit

        const seconds = timeValueToUse * TIME_MULTIPLIERS[unitToUse]

        onChange(seconds)
    }, [timeValue, unit])

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="number"
                value={timeValue ?? undefined}
                placeholder="0"
                min={0}
                autoFocus={autoFocus}
                step={1}
                onChange={(val) => {
                    const newValue = val
                    setTimeValue(newValue || 0)
                }}
            />
            <LemonSelect
                value={unit}
                onChange={(newValue) => {
                    setUnit(newValue as SmallTimeUnit)
                }}
                options={durationOptions.map((value) => ({ value, label: value }))}
            />
        </div>
    )
}
