import { kea } from 'kea'
import { Duration, TimeUnit } from '~/types'

import type { durationPickerLogicType } from './durationPickerLogicType'

export interface DurationPickerProps {
    onChange: (value_seconds: number) => void
    key: string | undefined
    initialValue: number
}

const TIME_MULTIPLIERS: Record<TimeUnit, number> = { seconds: 1, minutes: 60, hours: 3600 }

export const convertSecondsToDuration = (seconds: number): Duration => {
    const orderOfUnitsToTest: TimeUnit[] = ['hours', 'minutes']
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

export const durationPickerLogic = kea<durationPickerLogicType>({
    path: ['lib', 'components', 'DurationPicker', 'durationPickerLogic'],
    key: (props) => props.key || 'global',
    props: {} as DurationPickerProps,
    actions: {
        setTimeValue: (timeValue: number | undefined) => ({ timeValue }),
        setUnit: (unit: TimeUnit) => ({ unit }),
    },

    reducers: ({ props }) => ({
        unit: [
            props.initialValue ? convertSecondsToDuration(props.initialValue).unit : ('minutes' as TimeUnit),
            {
                setUnit: (_, { unit }) => unit,
            },
        ],
        timeValue: [
            convertSecondsToDuration(props.initialValue).timeValue as number | undefined,
            {
                setTimeValue: (_, { timeValue }) => timeValue,
            },
        ],
    }),

    listeners: ({ props, values }) => {
        const handleChange = ({ timeValue, unit }: { timeValue?: number | undefined; unit?: TimeUnit }): void => {
            const timeValueToUse = timeValue || values.timeValue || 0
            const unitToUse = unit || values.unit

            const seconds = timeValueToUse * TIME_MULTIPLIERS[unitToUse]

            props.onChange(seconds)
        }
        return {
            setTimeValue: ({ timeValue }) => handleChange({ timeValue }),
            setUnit: ({ unit }) => handleChange({ unit }),
        }
    },
})
