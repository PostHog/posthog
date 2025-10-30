import './RollingDateRangeFilter.scss'

import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { Dayjs } from 'lib/dayjs'
import { dateFilterToText } from 'lib/utils'

import type { rollingDateRangeFilterLogicType } from './rollingDateRangeFilterLogicType'

const dateOptionsMap = {
    y: 'years',
    q: 'quarters',
    m: 'months',
    w: 'weeks',
    d: 'days',
    h: 'hours',
    M: 'minutes',
    s: 'seconds',
} as const

export type DateOption = (typeof dateOptionsMap)[keyof typeof dateOptionsMap]

export type RollingDateFilterLogicPropsType = {
    inUse?: boolean
    onChange?: (fromDate: string) => void
    dateFrom?: Dayjs | string | null
    max?: number | null
    pageKey?: string
}

const counterDefault = (dateFrom: Dayjs | string | null | undefined): number => {
    if (dateFrom && typeof dateFrom === 'string') {
        const counter = parseInt(dateFrom.slice(1, -1))
        if (counter) {
            return counter
        }
    }
    return 3
}

const dateOptionDefault = (dateFrom: Dayjs | string | null | undefined): DateOption => {
    if (dateFrom && typeof dateFrom === 'string') {
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
        setDateOption: (option: DateOption) => ({ option }),
        toggleDateOptionsSelector: true,
        select: true,
    }),
    reducers(({ props }) => ({
        counter: [
            counterDefault(props.dateFrom) as number | null,
            {
                increaseCounter: (state) => (state ? (!props.max || state < props.max ? state + 1 : state) : 1),
                decreaseCounter: (state) => {
                    if (state) {
                        return state > 0 ? state - 1 : 0
                    }
                    return 0
                },
                setCounter: (prevCounter, { counter }) => {
                    if (counter) {
                        /** Relative dates must be expressed as integers
                         * @see {isStringDateRegex} */
                        counter = Math.round(counter)
                    }
                    return counter ? (!props.max || counter <= props.max ? counter : prevCounter) : null
                },
            },
        ],
        dateOption: [
            dateOptionDefault(props.dateFrom),
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
            (counter, dateOption) => {
                if (!counter) {
                    return ''
                }
                switch (dateOption) {
                    case 'years':
                        return `-${counter}y`
                    case 'quarters':
                        return `-${counter}q`
                    case 'months':
                        return `-${counter}m`
                    case 'weeks':
                        return `-${counter}w`
                    case 'days':
                        return `-${counter}d`
                    case 'hours':
                        return `-${counter}h`
                    case 'minutes':
                        return `-${counter}M`
                    case 'seconds':
                        return `-${counter}s`
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
                return dateFilterToText(
                    value,
                    undefined,
                    'N/A',
                    [],
                    false,
                    value.slice(-1) === 'h' ? 'MMMM D, YYYY HH:mm:ss' : 'MMMM D, YYYY',
                    true
                )
            },
        ],
    })),
    listeners(({ props, values, actions }) => ({
        select: async (_val, breakpoint) => {
            await breakpoint(500) // give some extra debounce time, because the menu is fiddly
            props.onChange?.(values.value)
        },
        setDateOption: () => {
            actions.select()
        },
        setCounter: () => {
            actions.select()
        },
        increaseCounter: () => {
            actions.select()
        },
        decreaseCounter: () => {
            actions.select()
        },
    })),
])
