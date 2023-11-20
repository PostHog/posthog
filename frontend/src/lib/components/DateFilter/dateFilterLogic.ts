import { actions, props, kea, listeners, path, reducers, selectors, key } from 'kea'
import { dayjs, Dayjs } from 'lib/dayjs'
import type { dateFilterLogicType } from './dateFilterLogicType'
import { isDate, dateFilterToText, dateStringToDayJs, formatDateRange, formatDate } from 'lib/utils'
import { DateMappingOption } from '~/types'
import { DateFilterLogicProps, DateFilterView } from 'lib/components/DateFilter/types'

export const CUSTOM_OPTION_KEY = 'Custom'
export const CUSTOM_OPTION_VALUE = 'No date range override'
export const CUSTOM_OPTION_DESCRIPTION = 'Use the original date ranges of insights'

export const dateFilterLogic = kea<dateFilterLogicType>([
    path(['lib', 'components', 'DateFilter', 'DateFilterLogic']),
    props({} as DateFilterLogicProps),
    key(({ key }) => key),
    actions({
        open: true,
        openFixedRange: true,
        openDateToNow: true,
        close: true,
        applyRange: true,
        setDate: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setRangeDateFrom: (range: Dayjs | null) => ({ range }),
        setRangeDateTo: (range: Dayjs | null) => ({ range }),
    }),
    reducers(({ props }) => ({
        view: [
            DateFilterView.QuickList as DateFilterView,
            {
                open: () => DateFilterView.QuickList,
                openFixedRange: () => DateFilterView.FixedRange,
                openDateToNow: () => DateFilterView.DateToNow,
            },
        ],
        isVisible: [
            false,
            {
                open: () => true,
                openFixedRange: () => true,
                openDateToNow: () => true,
                setDate: () => false,
                close: () => false,
            },
        ],
        rangeDateFrom: [
            (props.dateFrom && (dayjs.isDayjs(props.dateFrom) || isDate.test(props.dateFrom))
                ? dayjs(props.dateFrom)
                : null) as Dayjs | null,
            {
                setRangeDateFrom: (_, { range }) => (range ? dayjs(range) : null),
                setDate: (_, { dateFrom }) => dateStringToDayJs(dateFrom),
            },
        ],
        rangeDateTo: [
            (props.dateTo && (dayjs.isDayjs(props.dateTo) || isDate.test(props.dateTo))
                ? dayjs(props.dateTo)
                : dayjs()) as Dayjs | null,
            {
                setRangeDateTo: (_, { range }) => (range ? dayjs(range) : null),
                setDate: (_, { dateTo }) => (dateTo ? dateStringToDayJs(dateTo) : null),
            },
        ],
    })),
    selectors({
        dateFrom: [() => [(_, props) => props.dateFrom], (dateFrom) => dateFrom ?? null],
        dateTo: [() => [(_, props) => props.dateTo], (dateTo) => dateTo ?? null],
        dateOptions: [
            () => [(_, props) => props.dateOptions],
            (dateOptions): DateMappingOption[] | undefined => dateOptions,
        ],
        isFixedRange: [
            (s) => [s.dateFrom, s.dateTo],
            (dateFrom, dateTo) => !!(dateFrom && dateTo && dayjs(dateFrom).isValid() && dayjs(dateTo).isValid()),
        ],
        isDateToNow: [
            (s) => [s.dateFrom, s.dateTo],
            (dateFrom, dateTo) => !!dateFrom && !dateTo && dayjs(dateFrom).isValid(),
        ],
        isRollingDateRange: [
            (s) => [s.isFixedRange, s.isDateToNow, s.dateOptions, s.dateFrom, s.dateTo],
            (isFixedRange, isDateToNow, dateOptions, dateFrom, dateTo): boolean =>
                !isFixedRange &&
                !isDateToNow &&
                !dateOptions?.find(
                    (option) =>
                        (option.values[0] ?? null) === (dateFrom ?? null) &&
                        (option.values[1] ?? null) === (dateTo ?? null)
                ),
        ],
        label: [
            (s) => [s.dateFrom, s.dateTo, s.isFixedRange, s.isDateToNow, s.dateOptions],
            (dateFrom, dateTo, isFixedRange, isDateToNow, dateOptions) =>
                isFixedRange
                    ? formatDateRange(dayjs(dateFrom), dayjs(dateTo))
                    : isDateToNow
                    ? `${formatDate(dayjs(dateFrom))} to now`
                    : dateFilterToText(dateFrom, dateTo, CUSTOM_OPTION_VALUE, dateOptions, false),
        ],
    }),
    listeners(({ actions, values, props }) => ({
        applyRange: () => {
            if (values.rangeDateFrom) {
                actions.setDate(
                    dayjs(values.rangeDateFrom).format('YYYY-MM-DD'),
                    values.rangeDateTo ? dayjs(values.rangeDateTo).format('YYYY-MM-DD') : null
                )
            }
        },
        setDate: ({ dateFrom, dateTo }) => {
            props.onChange?.(dateFrom, dateTo)
        },
    })),
])
