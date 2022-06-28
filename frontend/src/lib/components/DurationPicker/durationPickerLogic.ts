import { kea } from 'kea'
import { Duration, SmallTimeUnit } from '~/types'

import type { durationPickerLogicType } from './durationPickerLogicType'

export interface DurationPickerLogicProps {
    onChange: (value_seconds: number) => void
    pageKey: string | undefined
    initialValue?: number
}

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

export const durationPickerLogic = kea<durationPickerLogicType>({
    path: ['lib', 'components', 'DurationPicker', 'durationPickerLogic'],
    key: (props) => props.pageKey || 'global',
    props: {} as DurationPickerLogicProps,
    actions: {
        setTimeValue: (timeValue: number | null) => ({ timeValue }),
        setUnit: (unit: SmallTimeUnit) => ({ unit }),
    },

    reducers: ({ props }) => ({
        unit: [
            (props.initialValue ? convertSecondsToDuration(props.initialValue).unit : 'minutes') as SmallTimeUnit,
            {
                setUnit: (_, { unit }) => unit,
            },
        ],
        timeValue: [
            (props.initialValue ? convertSecondsToDuration(props.initialValue).timeValue : null) as number | null,
            {
                setTimeValue: (_, { timeValue }) => timeValue,
            },
        ],
    }),

    listeners: ({ props, values }) => {
        const handleChange = ({ timeValue, unit }: { timeValue?: number | null; unit?: SmallTimeUnit }): void => {
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
