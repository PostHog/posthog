import { kea } from 'kea'
import { PropertyOperator, RecordingDurationFilter } from '~/types'
import { durationFilterLogicType } from './durationFilterLogicType'

export enum TimeUnit {
    SECONDS = 'seconds',
    MINUTES = 'minutes',
    HOURS = 'hours',
}

export interface DurationFilterProps {
    onChange: (value: RecordingDurationFilter) => void
    pageKey: string | undefined
    initialFilter: RecordingDurationFilter
}

const TIME_MULTIPLIERS = { seconds: 1, minutes: 60, hours: 3600 }

export const durationFilterLogic = kea<durationFilterLogicType<DurationFilterProps, TimeUnit>>({
    path: (key) => ['scenes', 'session-recordings', 'DurationFilterLogic', key],
    key: (props) => props.pageKey || 'global',
    props: {} as DurationFilterProps,
    actions: {
        setTimeValue: (timeValue: number) => ({ timeValue }),
        setUnit: (unit: TimeUnit) => ({ unit }),
        setIsOpen: (isOpen: boolean) => ({ isOpen }),
        setOperator: (operator: PropertyOperator) => ({ operator }),
    },

    reducers: ({ props }) => ({
        unit: [
            TimeUnit.MINUTES as TimeUnit,
            {
                setUnit: (_, { unit }) => unit,
            },
        ],
        operator: [
            props?.initialFilter?.operator,
            {
                setOperator: (_, { operator }) => operator,
            },
        ],
        timeValue: [
            Math.floor(props.initialFilter.value / TIME_MULTIPLIERS[TimeUnit.MINUTES]),
            {
                setTimeValue: (_, { timeValue }) => timeValue,
            },
        ],
        isOpen: [
            false,
            {
                setIsOpen: (_, { isOpen }) => isOpen,
            },
        ],
    }),

    selectors: {
        durationString: [
            (s) => [s.operator, s.timeValue, s.unit],
            (operator, timeValue, unit) => {
                let durationString = ''
                if (operator === PropertyOperator.GreaterThan) {
                    durationString += '> '
                } else {
                    durationString += '< '
                }
                durationString += timeValue
                if (timeValue === 1) {
                    durationString += ' ' + unit.slice(0, -1)
                } else {
                    durationString += ' ' + unit
                }
                return durationString
            },
        ],
    },

    listeners: ({ props, values }) => {
        const handleChange = ({
            timeValue,
            unit,
            operator,
        }: {
            timeValue?: number
            unit?: TimeUnit
            operator?: PropertyOperator
        }): void => {
            const timeValueToUse = timeValue || values.timeValue
            const unitToUse = unit || values.unit

            const seconds = timeValueToUse * TIME_MULTIPLIERS[unitToUse]

            props.onChange({
                operator: operator || values.operator,
                value: seconds,
                type: 'recording',
                key: 'duration',
            })
        }
        return {
            setTimeValue: ({ timeValue }) => handleChange({ timeValue }),
            setUnit: ({ unit }) => handleChange({ unit }),
            setOperator: ({ operator }) => handleChange({ operator }),
        }
    },
})
