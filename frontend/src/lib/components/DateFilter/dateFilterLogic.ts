import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import {
    DateFilterLogicProps,
    DateFilterView,
    NO_OVERRIDE_RANGE_PLACEHOLDER,
    SELECT_FIXED_VALUE_PLACEHOLDER,
} from 'lib/components/DateFilter/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import {
    dateFilterToText,
    dateStringToDayJs,
    formatDate,
    formatDateRange,
    formatDateTime,
    formatDateTimeRange,
    isDate,
} from 'lib/utils'

import { DateMappingOption } from '~/types'

import type { dateFilterLogicType } from './dateFilterLogicType'

const RELATIVE_UNIT_LABEL: Record<string, string> = {
    h: 'hour',
    d: 'day',
    w: 'week',
    m: 'month',
    q: 'quarter',
    y: 'year',
}

function formatRelativeOffset(value: string): string {
    const match = /^-(\d+)([hdwmqy])$/.exec(value)
    if (!match) {
        return value
    }
    const n = Number.parseInt(match[1], 10)
    const unit = RELATIVE_UNIT_LABEL[match[2]] ?? 'day'
    return `${n} ${unit}${n === 1 ? '' : 's'} ago`
}

/** Check if a date value has time precision (non-midnight time component) */
function hasTimePrecision(dateValue: string | Dayjs | null | undefined): boolean {
    if (!dateValue) {
        return false
    }
    if (dayjs.isDayjs(dateValue)) {
        return dateValue.format('HH:mm:ss') !== '00:00:00'
    }
    if (typeof dateValue === 'string' && isDate.test(dateValue)) {
        return dayjs(dateValue).format('HH:mm:ss') !== '00:00:00'
    }
    return false
}

export const dateFilterLogic = kea<dateFilterLogicType>([
    path(['lib', 'components', 'DateFilter', 'DateFilterLogic']),
    props({} as DateFilterLogicProps),
    key(({ key }) => key),
    actions({
        open: true,
        openFixedRange: true,
        openFixedRangeWithTime: true,
        openDateToNow: true,
        openFixedDate: true,
        openJumpToTimestamp: true,
        openCustomRelativeRange: true,
        close: true,
        applyRange: true,
        setFixedRangeGranularity: (granularity: 'day' | 'minute') => ({ granularity }),
        setDate: (
            dateFrom: string | null,
            dateTo: string | null,
            keepPopoverOpen = false,
            explicitDate: boolean = false
        ) => ({
            dateFrom,
            dateTo,
            keepPopoverOpen,
            explicitDate,
        }),
        setRangeDateFrom: (range: Dayjs | null) => ({ range }),
        setRangeDateTo: (range: Dayjs | null) => ({ range }),
        setExplicitDate: (explicitDate: boolean) => ({ explicitDate }),
    }),
    reducers(({ props }) => ({
        view: [
            DateFilterView.QuickList as DateFilterView,
            {
                open: () => DateFilterView.QuickList,
                openFixedRange: () => DateFilterView.FixedRange,
                openFixedRangeWithTime: () => DateFilterView.FixedRangeWithTime,
                openDateToNow: () => DateFilterView.DateToNow,
                openFixedDate: () => DateFilterView.FixedDate,
                openJumpToTimestamp: () => DateFilterView.JumpToTimestamp,
                openCustomRelativeRange: () => DateFilterView.CustomRelativeRange,
            },
        ],
        isVisible: [
            false,
            {
                open: () => true,
                openFixedRange: () => true,
                openFixedRangeWithTime: () => true,
                openDateToNow: () => true,
                openFixedDate: () => true,
                openJumpToTimestamp: () => true,
                openCustomRelativeRange: () => true,
                setDate: (_, { keepPopoverOpen }) => keepPopoverOpen,
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
        explicitDate: [
            props.explicitDate ?? hasTimePrecision(props.dateFrom),
            {
                setExplicitDate: (_, { explicitDate }) => explicitDate,
                setDate: (_, { explicitDate }) => explicitDate,
            },
        ],
        fixedRangeGranularity: [
            // Default based on whether the current dateFrom has time precision
            (hasTimePrecision(props.dateFrom) ? 'minute' : 'day') as 'day' | 'minute',
            {
                setFixedRangeGranularity: (_, { granularity }) => granularity,
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
        isFixedRangeWithTime: [
            (s) => [s.isFixedRange, s.dateFromHasTimePrecision, s.dateToHasTimePrecision],
            (isFixedRange, dateFromHasTimePrecision, dateToHasTimePrecision) =>
                isFixedRange && (dateFromHasTimePrecision || dateToHasTimePrecision),
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
        isCustomRelativeRange: [
            (s) => [s.dateFrom, s.dateTo],
            (dateFrom, dateTo): boolean => {
                // Check if both dates are in relative format (e.g., "-30d", "-7d")
                const isRelativeFromDate = typeof dateFrom === 'string' && /^-\d+[hdwmqy]$/.test(dateFrom)
                const isRelativeToDate = typeof dateTo === 'string' && /^-\d+[hdwmqy]$/.test(dateTo)
                return isRelativeFromDate && isRelativeToDate && !!dateFrom && !!dateTo
            },
        ],
        isCustomRelativeRangeView: [(s) => [s.view], (view): boolean => view === DateFilterView.CustomRelativeRange],
        dateFromHasTimePrecision: [(s) => [s.dateFrom], (dateFrom) => hasTimePrecision(dateFrom)],
        dateToHasTimePrecision: [(s) => [s.dateTo], (dateTo) => hasTimePrecision(dateTo)],
        label: [
            (s) => [
                s.dateFrom,
                s.dateTo,
                s.isFixedRange,
                s.isDateToNow,
                s.isFixedDate,
                s.isCustomRelativeRange,
                s.dateOptions,
                (_, p) => p.isFixedDateMode,
                (_, p) => p.placeholder,
                (_, p) => p.allowTimePrecision,
                (_, p) => p.showCustomRelativeRange,
                (_, p) => p.allowSingleAndRange,
                s.dateFromHasTimePrecision,
                s.dateToHasTimePrecision,
            ],
            (
                dateFrom,
                dateTo,
                isFixedRange,
                isDateToNow,
                isFixedDate,
                isCustomRelativeRange,
                dateOptions,
                isFixedDateMode,
                placeholder,
                allowTimePrecision,
                showCustomRelativeRange,
                allowSingleAndRange,
                dateFromHasTimePrecision,
                dateToHasTimePrecision
            ) => {
                // Only render the "N days ago to M days ago" label when the consumer has opted into
                // the custom-relative-range picker — other call sites (e.g. trends) may legitimately
                // store both dates as relative strings (e.g. "-0d"/"-0d" for "Today") without intending
                // the two-offset semantic, and should fall through to dateFilterToText.
                if (
                    showCustomRelativeRange &&
                    isCustomRelativeRange &&
                    typeof dateFrom === 'string' &&
                    typeof dateTo === 'string'
                ) {
                    return `${formatRelativeOffset(dateFrom)} to ${formatRelativeOffset(dateTo)}`
                }
                // When the consumer allows both single and range selections, render an absolute
                // single-bound value as just the formatted date rather than "X to now" — picking
                // a custom date should not visually imply a range. Time is preserved when the
                // picked value has it (the single-date picker lets users include a time), whereas
                // ranges still require the explicit `allowTimePrecision` opt-in.
                if (
                    allowSingleAndRange &&
                    dateFrom &&
                    !dateTo &&
                    typeof dateFrom === 'string' &&
                    !/^-\d+[hdwmqy]/.test(dateFrom) &&
                    dayjs(dateFrom).isValid()
                ) {
                    return dateFromHasTimePrecision ? formatDateTime(dayjs(dateFrom)) : formatDate(dayjs(dateFrom))
                }
                const renderWithTime = allowTimePrecision && (dateFromHasTimePrecision || dateToHasTimePrecision)
                return isFixedRange
                    ? renderWithTime
                        ? formatDateTimeRange(dayjs(dateFrom), dayjs(dateTo))
                        : formatDateRange(dayjs(dateFrom), dayjs(dateTo))
                    : isDateToNow
                      ? `${
                            // Preserve pre-PR behavior: honour time precision based on the stored
                            // value alone. `allowTimePrecision` gating only applies to range
                            // rendering (to keep fixed ranges date-only in the cohort field).
                            dateFromHasTimePrecision ? formatDateTime(dayjs(dateFrom)) : formatDate(dayjs(dateFrom))
                        } to now`
                      : isFixedDate
                        ? formatDate(dateStringToDayJs(dateFrom) ?? dayjs(dateFrom))
                        : dateFilterToText(
                              dateFrom,
                              dateTo,
                              isFixedDateMode
                                  ? (placeholder ?? SELECT_FIXED_VALUE_PLACEHOLDER)
                                  : NO_OVERRIDE_RANGE_PLACEHOLDER,
                              dateOptions,
                              false
                          )
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        applyRange: () => {
            if (values.rangeDateFrom) {
                actions.setDate(
                    dayjs(values.rangeDateFrom).format(props.allowTimePrecision ? 'YYYY-MM-DDTHH:mm:ss' : 'YYYY-MM-DD'),
                    // Treat as naive time. Project timezone will be applied on backend.
                    values.rangeDateTo ? dayjs(values.rangeDateTo).format('YYYY-MM-DDTHH:mm:ss') : null,
                    false,
                    values.explicitDate || false
                )
            }
        },
        setDate: ({ dateFrom, dateTo, explicitDate }) => {
            // Normalise empty-string to null so consumers (e.g. cohort criteria) don't persist
            // semantically-empty upper bounds. Several call sites still pass `''` for "no bound".
            const normalisedFrom = dateFrom === '' ? null : dateFrom
            const normalisedTo = dateTo === '' ? null : dateTo
            props.onChange?.(normalisedFrom, normalisedTo, explicitDate)
        },
        setExplicitDate: ({ explicitDate }) => {
            props.onChange?.(values.dateFrom, values.dateTo, explicitDate)
        },
    })),
])
