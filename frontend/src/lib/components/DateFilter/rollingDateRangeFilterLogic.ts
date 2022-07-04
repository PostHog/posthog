import { actions, props, kea, listeners, path, reducers, selectors } from 'kea'
import type { rollingDateRangeFilterLogicType } from './rollingDateRangeFilterLogicType'
import { Dayjs } from 'lib/dayjs'
import './RollingDateRangeFilter.scss'
import { dateFilterToText } from 'lib/utils'

const dateOptionsMap = {
    q: 'quarters',
    m: 'months',
    w: 'weeks',
    d: 'days',
}

export type RollingDateFilterLogicPropsType = {
    selected?: boolean
    onChange?: (fromDate: string) => void
    dateFrom?: Dayjs | string | null
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
                increaseCounter: (state) => (state ? state + 1 : 1),
                decreaseCounter: (state) => {
                    if (state) {
                        return state > 0 ? state - 1 : 0
                    }
                    return 0
                },
                setCounter: (_, { counter }) => counter ?? null,
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
