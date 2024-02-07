import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import {
    DateFilterLogicProps,
    DateFilterView,
    NO_OVERRIDE_RANGE_PLACEHOLDER,
    SELECT_FIXED_VALUE_PLACEHOLDER,
} from 'lib/components/DateFilter/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { dateFilterToText, dateStringToDayJs, formatDate, formatDateRange, isDate } from 'lib/utils'

import { DateMappingOption } from '~/types'

import type { dateFilterLogicType } from './dateFilterLogicType'

export const dateFilterLogic = kea<dateFilterLogicType>([
    path(['lib', 'components', 'DateFilter', 'DateFilterLogic']),
    props({} as DateFilterLogicProps),
    key(({ key }) => key),
    actions({
        open: true,
        openFixedRange: true,
        openDateToNow: true,
        openFixedDate: true,
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
                openFixedDate: () => DateFilterView.FixedDate,
            },
        ],
        isVisible: [
            false,
            {
                open: () => true,
                openFixedRange: () => true,
                openDateToNow: () => true,
                openFixedDate: () => true,
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
            (s) => [s.dateFrom, s.dateTo, (_, p) => p.isFixedDateMode],
            (dateFrom, dateTo, isFixedDateMode) =>
                !!dateFrom && !dateTo && dayjs(dateFrom).isValid() && !isFixedDateMode,
        ],
        isFixedDate: [
            (s) => [s.dateFrom, s.dateTo, (_, p) => p.isFixedDateMode],
            (dateFrom, dateTo, isFixedDateMode) => dateFrom && dayjs(dateFrom).isValid() && !dateTo && isFixedDateMode,
        ],
        isRollingDateRange: [
            (s) => [s.isFixedRange, s.isDateToNow, s.isFixedDate, s.dateOptions, s.dateFrom, s.dateTo],
            (isFixedRange, isDateToNow, isFixedDate, dateOptions, dateFrom, dateTo): boolean =>
                !isFixedRange &&
                !isDateToNow &&
                !isFixedDate &&
                !dateOptions?.find(
                    (option) =>
                        (option.values[0] ?? null) === (dateFrom ?? null) &&
                        (option.values[1] ?? null) === (dateTo ?? null)
                ),
        ],
        label: [
            (s) => [
                s.dateFrom,
                s.dateTo,
                s.isFixedRange,
                s.isDateToNow,
                s.isFixedDate,
                s.dateOptions,
                (_, p) => p.isFixedDateMode,
            ],
            (dateFrom, dateTo, isFixedRange, isDateToNow, isFixedDate, dateOptions, isFixedDateMode) =>
                isFixedRange
                    ? formatDateRange(dayjs(dateFrom), dayjs(dateTo))
                    : isDateToNow
                    ? `${formatDate(dayjs(dateFrom))} to now`
                    : isFixedDate
                    ? formatDate(dateStringToDayJs(dateFrom) ?? dayjs(dateFrom))
                    : dateFilterToText(
                          dateFrom,
                          dateTo,
                          isFixedDateMode ? SELECT_FIXED_VALUE_PLACEHOLDER : NO_OVERRIDE_RANGE_PLACEHOLDER,
                          dateOptions,
                          false
                      ),
        ],
    }),
    listeners(({ actions, values, props }) => ({
        applyRange: () => {
            if (values.rangeDateFrom) {
                actions.setDate(
                    dayjs(values.rangeDateFrom).format('YYYY-MM-DD'),
                    values.rangeDateTo ? dayjs(values.rangeDateTo).format() : null
                )
            }
        },
        setDate: ({ dateFrom, dateTo }) => {
            props.onChange?.(dateFrom, dateTo)
        },
    })),
])
