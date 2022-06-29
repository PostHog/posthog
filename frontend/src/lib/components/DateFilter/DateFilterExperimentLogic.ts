import { dayjs, Dayjs } from 'lib/dayjs'
import { kea } from 'kea'
import type { dateFilterLogicType } from './DateFilterExperimentLogicType'
import { isDate, dateFilterToText } from 'lib/utils'
import { dateMappingOption } from '~/types'

export type DateFilterLogicPropsType = {
    defaultValue: string
    onChange?: (fromDate: string, toDate: string) => void
    dateFrom?: Dayjs | string | null
    dateTo?: Dayjs | string | null
    dateOptions?: Record<string, dateMappingOption>
    isDateFormatted?: boolean
}

export const dateFilterLogic = kea<dateFilterLogicType>({
    path: ['lib', 'components', 'DateFilter', 'DateFilterLogic'],
    props: { defaultValue: 'Custom' } as DateFilterLogicPropsType,
    actions: {
        open: true,
        close: true,
        openDateRange: true,
        setDate: (dateFrom: string, dateTo: string) => ({ dateFrom, dateTo }),
        setRangeDateFrom: (range: Dayjs | string | undefined | null) => ({ range }),
        setRangeDateTo: (range: Dayjs | string | undefined | null) => ({ range }),
        setValue: (value: string) => ({ value }),
    },
    defaults: ({ props }) => ({
        value: dateFilterToText(props.dateFrom, props.dateTo, props.defaultValue, props.dateOptions, false),
    }),
    reducers: ({ props, defaults }) => ({
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
            props.dateFrom && isDate.test(props.dateFrom as string)
                ? dayjs(props.dateFrom)
                : (undefined as Dayjs | string | undefined | null),
            {
                setRangeDateFrom: (_, { range }) => range,
                openDateRange: () => null,
            },
        ],
        rangeDateTo: [
            props.dateTo && isDate.test(props.dateTo as string)
                ? dayjs(props.dateTo)
                : (dayjs().format('YYYY-MM-DD') as Dayjs | string | undefined | null),
            {
                setRangeDateTo: (_, { range }) => range,
                openDateRange: () => dayjs().format('YYYY-MM-DD'),
            },
        ],
        value: [
            defaults.value,
            {
                setValue: (_, { value }) => value,
            },
        ],
    }),
    listeners: ({ props }) => ({
        setDate: ({ dateFrom, dateTo }) => {
            props.onChange && props.onChange(dateFrom, dateTo)
        },
    }),
    events: ({ actions, values }) => ({
        propsChanged: (props) => {
            // when props change, automatically reset the Select key to reflect the change
            const { dateFrom, dateTo, defaultValue, dateOptions, isDateFormatted } = props
            let newValue = null
            if (dateFrom && dayjs(dateFrom).isValid() && dayjs(dateTo).isValid()) {
                newValue = `${dateFrom} - ${dateTo}`
            } else {
                const currKey = dateFilterToText(dateFrom, dateTo, defaultValue, dateOptions, false)
                newValue =
                    isDateFormatted && !(currKey in dateOptions)
                        ? dateFilterToText(dateFrom, dateTo, defaultValue, dateOptions, true)
                        : currKey
            }
            if (newValue && values.value !== newValue) {
                actions.setValue(newValue)
            }
        },
    }),
})
