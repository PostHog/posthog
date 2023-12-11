import './RollingDateRangeFilter.scss'

import { actions, kea, listeners, path, props, reducers, selectors } from 'kea'
import { Dayjs } from 'lib/dayjs'
import { dateFilterToText } from 'lib/utils'

import type { rollingDateRangeFilterLogicType } from './rollingDateRangeFilterLogicType'

const dateOptionsMap = {
    q: 'quarters',
    m: 'months',
    w: 'weeks',
    d: 'days',
} as const

export type DateOption = (typeof dateOptionsMap)[keyof typeof dateOptionsMap]

export type RollingDateFilterLogicPropsType = {
    selected?: boolean
    onChange?: (fromDate: string) => void
    dateFrom?: Dayjs | string | null
    max?: number | null
}

const counterDefault = (selected: boolean | undefined, dateFrom: Dayjs | string | null | undefined): number => {
    if (selected && dateFrom && typeof dateFrom === 'string') {
        const counter = parseInt(dateFrom.slice(1, -1))
        if (counter) {
            return counter
        }
    }
    return 3
}

const dateOptionDefault = (selected: boolean | undefined, dateFrom: Dayjs | string | null | undefined): string => {
    if (selected && dateFrom && typeof dateFrom === 'string') {
        const dateOption = dateOptionsMap[dateFrom.slice(-1)]
        if (dateOption) {
            return dateOption
        }
    }
    return 'days'
}

export const rollingDateRangeFilterLogic = kea<rollingDateRangeFilterLogicType>([
    path(['lib', 'components', 'DateFilter', 'RollingDateRangeFilterLogic']),
    actions({
        increaseCounter: true,
        decreaseCounter: true,
        setCounter: (counter: number | null | undefined) => ({ counter }),
        setDateOption: (option: string) => ({ option }),
        toggleDateOptionsSelector: true,
        select: true,
    }),
    props({} as RollingDateFilterLogicPropsType),
    reducers(({ props }) => ({
        counter: [
            counterDefault(props.selected, props.dateFrom) as number | null,
            {
                increaseCounter: (state) => (state ? (!props.max || state < props.max ? state + 1 : state) : 1),
                decreaseCounter: (state) => {
                    if (state) {
                        return state > 0 ? state - 1 : 0
                    }
                    return 0
                },
                setCounter: (prevCounter, { counter }) =>
                    counter ? (!props.max || counter <= props.max ? counter : prevCounter) : null,
            },
        ],
        dateOption: [
            dateOptionDefault(props.selected, props.dateFrom),
            {
                setDateOption: (_, { option }) => option,
            },
        ],
        isDateOptionsSelectorOpen: [
            false,
            {
                toggleDateOptionsSelector: (state) => !state,
            },
        ],
    })),
    selectors(() => ({
        value: [
            (s) => [s.counter, s.dateOption],
            (counter: number | null, dateOption: string) => {
                if (!counter) {
                    return ''
                }
                switch (dateOption) {
                    case 'quarters':
                        return `-${counter}q`
                    case 'months':
                        return `-${counter}m`
                    case 'weeks':
                        return `-${counter}w`
                    default:
                        return `-${counter}d`
                }
            },
        ],
        formattedDate: [
            (s) => [s.value],
            (value: string) => {
                return dateFilterToText(value, undefined, 'Custom rolling range', [], true)
            },
        ],
    })),
    listeners(({ props, values }) => ({
        select: () => {
            props.onChange?.(values.value)
        },
    })),
])
