import { actions, props, kea, listeners, path, reducers, selectors, key } from 'kea'
import { dayjs, Dayjs } from 'lib/dayjs'
import type { dateFilterLogicType } from './dateFilterLogicType'
import { isDate, dateFilterToText, dateStringToDayJs } from 'lib/utils'
import { DateMappingOption } from '~/types'

export type DateFilterLogicPropsType = {
    key: string
    defaultValue: string
    onChange?: (fromDate: string, toDate: string) => void
    dateFrom?: Dayjs | string | null
    dateTo?: Dayjs | string | null
    dateOptions?: DateMappingOption[]
    isDateFormatted?: boolean
}

export const dateFilterLogic = kea<dateFilterLogicType>([
    path(['lib', 'components', 'DateFilter', 'DateFilterLogic']),
    props({ defaultValue: 'Custom' } as DateFilterLogicPropsType),
    key(({ key }) => key),
    actions({
        open: true,
        close: true,
        openDateRange: true,
        applyRange: true,
        setDate: (dateFrom: string, dateTo: string) => ({ dateFrom, dateTo }),
        setRangeDateFrom: (range: Dayjs | null) => ({ range }),
        setRangeDateTo: (range: Dayjs | null) => ({ range }),
    }),
    reducers(({ props }) => ({
        isOpen: [
            false,
            {
                open: () => true,
                close: () => false,
                openDateRange: () => false,
                setDate: () => false,
            },
        ],
        isDateRangeOpen: [
            false,
            {
                open: () => false,
                openDateRange: () => true,
                close: () => false,
                setDate: () => false,
            },
        ],
        rangeDateFrom: [
            (props.dateFrom && (dayjs.isDayjs(props.dateFrom) || isDate.test(props.dateFrom as string))
                ? dayjs(props.dateFrom)
                : null) as Dayjs | null,
            {
                setRangeDateFrom: (_, { range }) => (range ? dayjs(range) : null),
                setDate: (_, { dateFrom }) => (dateFrom ? dateStringToDayJs(dateFrom) : null),
            },
        ],
        rangeDateTo: [
            (props.dateTo && (dayjs.isDayjs(props.dateTo) || isDate.test(props.dateTo as string))
                ? dayjs(props.dateTo)
                : dayjs().format('YYYY-MM-DD')) as Dayjs | null,
            {
                setRangeDateTo: (_, { range }) => (range ? dayjs(range) : null),
                setDate: (_, { dateTo }) => (dateTo ? dateStringToDayJs(dateTo) : dayjs()),
            },
        ],
    })),
    selectors(() => ({
        dateFrom: [() => [(_, props) => props.dateFrom], (dateFrom) => dateFrom ?? null],
        dateTo: [() => [(_, props) => props.dateTo], (dateTo) => dateTo ?? null],
        defaultValue: [() => [(_, props) => props.defaultValue], (defaultValue) => defaultValue],
        dateOptions: [() => [(_, props) => props.dateOptions], (dateOptions) => dateOptions],
        isFixedDateRange: [
            (s) => [s.dateFrom, s.dateTo],
            (dateFrom, dateTo) => !!(dateFrom && dateTo && dayjs(dateFrom).isValid() && dayjs(dateTo).isValid()),
        ],
        isRollingDateRange: [
            (s) => [s.isFixedDateRange, s.dateOptions, s.dateFrom, s.dateTo],
            (
                isFixedDateRange: boolean,
                dateOptions: DateMappingOption[],
                dateFrom: Dayjs | string | null,
                dateTo: Dayjs | string | null
            ): boolean =>
                !isFixedDateRange &&
                !(
                    dateOptions &&
                    dateOptions.find(
                        (option) =>
                            (option.values[0] ?? null === dateFrom ?? null) &&
                            (option.values[1] ?? null === dateTo ?? null)
                    )
                ),
        ],
        value: [
            (s) => [s.dateFrom, s.dateTo, s.isFixedDateRange, s.defaultValue, s.dateOptions],
            (dateFrom, dateTo, isFixedDateRange, defaultValue, dateOptions) =>
                isFixedDateRange
                    ? `${dateFrom} - ${dateTo}`
                    : dateFilterToText(dateFrom, dateTo, defaultValue, dateOptions, true),
        ],
    })),
    listeners(({ actions, values, props }) => ({
        applyRange: () => {
            const formattedRangeDateFrom = dayjs(values.rangeDateFrom).format('YYYY-MM-DD')
            const formattedRangeDateTo = dayjs(values.rangeDateTo).format('YYYY-MM-DD')
            actions.setDate(formattedRangeDateFrom, formattedRangeDateTo)
        },
        setDate: ({ dateFrom, dateTo }) => {
            props.onChange?.(dateFrom, dateTo)
        },
    })),
])
