import { kea } from 'kea'
import { convertSecondsToDuration } from 'lib/components/DurationPicker/DurationPicker'
import { PropertyOperator, RecordingDurationFilter } from '~/types'
import type { durationFilterLogicType } from './durationFilterLogicType'

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

export const durationFilterLogic = kea<durationFilterLogicType>({
    path: (key) => ['scenes', 'session-recordings', 'DurationFilterLogic', key],
    key: (props) => props.pageKey || 'global',
    props: {} as DurationFilterProps,
    actions: {
        setValue: (value: number | null) => ({ value }),
        setIsOpen: (isOpen: boolean) => ({ isOpen }),
        setOperator: (operator: PropertyOperator) => ({ operator }),
    },

    reducers: ({ props }) => ({
        operator: [
            props?.initialFilter?.operator,
            {
                setOperator: (_, { operator }) => operator,
            },
        ],
        value: [
            props?.initialFilter?.value as number | null,
            {
                setValue: (_, { value }) => value,
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
            (s) => [s.operator, s.value],
            (operator, value) => {
                let durationString = ''
                if (operator === PropertyOperator.GreaterThan) {
                    durationString += '> '
                } else {
                    durationString += '< '
                }
                const duration = convertSecondsToDuration(value || 0)

                durationString += duration.timeValue || 0
                if (duration.timeValue === 1) {
                    durationString += ' ' + duration.unit.slice(0, -1)
                } else {
                    durationString += ' ' + duration.unit
                }
                return durationString
            },
        ],
    },

    listeners: ({ props, values }) => {
        const handleChange = ({ value, operator }: { value?: number | null; operator?: PropertyOperator }): void => {
            props.onChange({
                operator: operator || values.operator,
                value: value || values.value || 0,
                type: 'recording',
                key: 'duration',
            })
        }
        return {
            setValue: ({ value }) => handleChange({ value }),
            setOperator: ({ operator }) => handleChange({ operator }),
        }
    },
})
