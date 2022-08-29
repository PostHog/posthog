import { actions, props, kea, listeners, path, reducers, selectors, key } from 'kea'
import { dayjs, Dayjs } from 'lib/dayjs'
import type { dateFilterLogicType } from './dateFilterLogicType'
import { isDate, dateFilterToText, dateStringToDayJs } from 'lib/utils'
import { DateMappingOption } from '~/types'
import { DateFilterLogicProps, DateFilterView } from 'lib/components/DateFilter/types'

export const dateFilterLogic = kea<dateFilterLogicType>([
    path(['lib', 'components', 'DateFilter', 'DateFilterLogic']),
    props({ defaultValue: 'Custom' } as DateFilterLogicProps),
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
            DateFilterView.QuickList,
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
                : dayjs()) as Dayjs | null,
            {
                setRangeDateTo: (_, { range }) => (range ? dayjs(range) : null),
                setDate: (_, { dateTo }) => (dateTo ? dateStringToDayJs(dateTo) : dayjs()),
            },
        ],
    })),
    selectors({
        dateFrom: [() => [(_, props) => props.dateFrom], (dateFrom) => dateFrom ?? null],
        dateTo: [() => [(_, props) => props.dateTo], (dateTo) => dateTo ?? null],
        defaultValue: [() => [(_, props) => props.defaultValue], (defaultValue) => defaultValue],
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
            (dateFrom, dateTo) => dateFrom && !dateTo && dayjs(dateFrom).isValid(),
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
        value: [
            (s) => [s.dateFrom, s.dateTo, s.isFixedRange, s.isDateToNow, s.defaultValue, s.dateOptions],
            (dateFrom, dateTo, isFixedRange, isDateToNow, defaultValue, dateOptions) =>
                isFixedRange
                    ? `${dateFrom} - ${dateTo}`
                    : isDateToNow
                    ? `${dateFrom} to Now`
                    : dateFilterToText(dateFrom, dateTo, defaultValue, dateOptions, true),
        ],
    }),
    listeners(({ actions, values, props }) => ({
        applyRange: () => {
            actions.setDate(
                values.rangeDateFrom ? dayjs(values.rangeDateFrom).format('YYYY-MM-DD') : null,
                values.rangeDateTo ? dayjs(values.rangeDateTo).format('YYYY-MM-DD') : null
            )
        },
        setDate: ({ dateFrom, dateTo }) => {
            props.onChange?.(dateFrom, dateTo)
        },
    })),
])
