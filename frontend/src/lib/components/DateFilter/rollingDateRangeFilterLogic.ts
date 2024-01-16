import './RollingDateRangeFilter.scss'

import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
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
    forceUpdateDefaults?: boolean
    pageKey?: string
}

const counterDefault = (
    selected: boolean | undefined,
    shouldUpdate: boolean | undefined,
    dateFrom: Dayjs | string | null | undefined
): number => {
    const shouldUpdateDefaults = shouldUpdate ?? selected
    if (shouldUpdateDefaults && dateFrom && typeof dateFrom === 'string') {
        const counter = parseInt(dateFrom.slice(1, -1))
        if (counter) {
            return counter
        }
    }
    return 3
}

const dateOptionDefault = (
    selected: boolean | undefined,
    shouldUpdate: boolean | undefined,
    dateFrom: Dayjs | string | null | undefined
): string => {
    const shouldUpdateDefaults = shouldUpdate ?? selected

    if (shouldUpdateDefaults && dateFrom && typeof dateFrom === 'string') {
        const dateOption = dateOptionsMap[dateFrom.slice(-1)]
        if (dateOption) {
            return dateOption
        }
    }
    return 'days'
}

export const rollingDateRangeFilterLogic = kea<rollingDateRangeFilterLogicType>([
    path(['lib', 'components', 'DateFilter', 'RollingDateRangeFilterLogic']),
    props({} as RollingDateFilterLogicPropsType),
    key(({ pageKey }) => pageKey ?? 'unknown'),
    actions({
        increaseCounter: true,
        decreaseCounter: true,
        setCounter: (counter: number | null | undefined) => ({ counter }),
        setDateOption: (option: string) => ({ option }),
        toggleDateOptionsSelector: true,
        select: true,
    }),
    reducers(({ props }) => ({
        counter: [
            counterDefault(props.selected, props.forceUpdateDefaults, props.dateFrom) as number | null,
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
            dateOptionDefault(props.selected, props.forceUpdateDefaults, props.dateFrom),
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
        startOfDateRange: [
            (s) => [s.value],
            (value: string) => {
                return dateFilterToText(value, undefined, 'Custom rolling range', [], false, 'MMMM D, YYYY', true)
            },
        ],
    })),
    propsChanged(({ actions, props }, oldProps) => {
        // TRICKY: This forces prop updates to update the counter as well, so we aren't stuck with old values
        // in the counter
        if (props.dateFrom !== oldProps.dateFrom && props.forceUpdateDefaults) {
            actions.setCounter(counterDefault(props.selected, props.forceUpdateDefaults, props.dateFrom))
            actions.setDateOption(dateOptionDefault(props.selected, props.forceUpdateDefaults, props.dateFrom))
        }
    }),
    listeners(({ props, values }) => ({
        select: () => {
            props.onChange?.(values.value)
        },
    })),
])
