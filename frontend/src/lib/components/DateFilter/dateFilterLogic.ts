import { actions, props, events, kea, listeners, path, reducers, selectors, key } from 'kea'
import { dayjs, Dayjs } from 'lib/dayjs'
import type { dateFilterLogicType } from './dateFilterLogicType'
import { isDate, dateFilterToText } from 'lib/utils'
import { dateMappingOption } from '~/types'

export type DateFilterLogicPropsType = {
    key: string
    defaultValue: string
    onChange?: (fromDate: string, toDate: string) => void
    dateFrom?: Dayjs | string | null
    dateTo?: Dayjs | string | null
    dateOptions?: dateMappingOption[]
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
        setDate: (dateFrom: string, dateTo: string) => ({ dateFrom, dateTo }),
        setRangeDateFrom: (range: Dayjs | string | undefined | null) => ({ range }),
        setRangeDateTo: (range: Dayjs | string | undefined | null) => ({ range }),
        setValue: (value: string) => ({ value }),
    }),
    reducers(({ props }) => ({
        isOpen: [
            false,
            {
                open: () => true,
                close: () => false,
                openDateRange: () => false,
            },
        ],
        isDateRangeOpen: [
            false,
            {
                open: () => false,
                openDateRange: () => true,
                close: () => false,
            },
        ],
        rangeDateFrom: [
            (props.dateFrom && isDate.test(props.dateFrom as string) ? dayjs(props.dateFrom) : undefined) as
                | Dayjs
                | string
                | undefined
                | null,
            {
                setRangeDateFrom: (_, { range }) => range,
                openDateRange: () => null,
            },
        ],
        rangeDateTo: [
            (props.dateTo && isDate.test(props.dateTo as string)
                ? dayjs(props.dateTo)
                : dayjs().format('YYYY-MM-DD')) as Dayjs | string | undefined | null,
            {
                setRangeDateTo: (_, { range }) => range,
                openDateRange: () => dayjs().format('YYYY-MM-DD'),
            },
        ],
        value: [
            dateFilterToText(props.dateFrom, props.dateTo, props.defaultValue, props.dateOptions, true),
            {
                setValue: (_, { value }) => value,
            },
        ],
    })),
    selectors(() => ({
        isFixedDateRange: [
            () => [(_, props) => props.dateFrom, (_, props) => props.dateTo],
            (dateFrom: Dayjs | string | null, dateTo: Dayjs | string | null) =>
                !!(dateFrom && dateTo && dayjs(dateFrom).isValid() && dayjs(dateTo).isValid()),
        ],
        isRollingDateRange: [
            (s) => [
                s.isFixedDateRange,
                (_, props) => props.dateOptions,
                (_, props) => props.dateFrom,
                (_, props) => props.dateTo,
            ],
            (
                isFixedDateRange: boolean,
                dateOptions: dateMappingOption[],
                dateFrom: Dayjs | string | undefined | null,
                dateTo: Dayjs | string | undefined | null
            ): boolean =>
                !isFixedDateRange &&
                !(
                    dateOptions &&
                    dateOptions.find((option) => option.values[0] === dateFrom && option.values[1] === dateTo)
                ),
        ],
    })),
    listeners(({ props }) => ({
        setDate: ({ dateFrom, dateTo }) => {
            props.onChange?.(dateFrom, dateTo)
        },
    })),
    events(({ actions, values }) => ({
        propsChanged: (props) => {
            // when props change, automatically reset the Select key to reflect the change
            const { dateFrom, dateTo, defaultValue, dateOptions } = props
            let newValue = null
            if (values.isFixedDateRange) {
                newValue = `${dateFrom} - ${dateTo}`
            } else {
                newValue = dateFilterToText(dateFrom, dateTo, defaultValue, dateOptions, false)
            }
            if (newValue && values.value !== newValue) {
                actions.setValue(newValue)
            }
        },
    })),
])
