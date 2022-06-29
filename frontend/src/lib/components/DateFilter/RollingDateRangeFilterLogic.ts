import type { rollingDateRangeFilterLogicType } from './RollingDateRangeFilterLogicType'
import { kea } from 'kea'
import { dayjs } from 'lib/dayjs'
import './RollingDateRangeFilter.scss'
import { dateFilterToText } from 'lib/utils'

const format = 'YYYY-MM-DD'

export const rollingDateRangeFilterLogic = kea<rollingDateRangeFilterLogicType>({
    path: ['lib', 'components', 'DateFilter', 'RollingDateRangeFilterLogic'],
    actions: {
        increaseCounter: true,
        decreaseCounter: true,
        setCounter: (counter: number | null | undefined) => ({ counter }),
        setDateOption: (option: string) => ({ option }),
        toggleDateOptionsSelector: true,
    },
    reducers: () => ({
        counter: [
            3 as number | null | undefined,
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
            'days',
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
    }),
    selectors: () => ({
        dateFrom: [
            (s) => [s.counter, s.dateOption],
            (counter: number | null, dateOption: string) => {
                if (!counter) {
                    return ''
                }
                switch (dateOption) {
                    case 'quarter':
                        return `${dayjs()
                            .subtract(counter * 3, 'M')
                            .format(format)}`
                    case 'months':
                        return `${dayjs().subtract(counter, 'M').format(format)}`
                    case 'weeks':
                        return `${dayjs()
                            .subtract(counter * 7, 'd')
                            .format(format)}`
                    default:
                        return `${dayjs().subtract(counter, 'd').format(format)}`
                }
            },
        ],
        dateTo: [
            () => [],
            () => {
                return `${dayjs().endOf('d').format(format)}`
            },
        ],
        formattedDate: [
            (s) => [s.dateFrom, s.dateTo],
            (dateFrom: string, dateTo: string) => {
                return dateFilterToText(
                    dateFrom,
                    undefined,
                    'Custom rolling range',
                    { rolling: { values: [dateFrom, dateTo] } },
                    true
                )
            },
        ],
    }),
})
