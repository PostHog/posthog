import { Dayjs } from 'lib/dayjs'

import { DateMappingOption } from '~/types'

export enum DateFilterView {
    QuickList = 'QuickList',
    DateToNow = 'DateToNow',
    FixedRange = 'FixedRange',
    FixedDate = 'FixedDate',
}

export type DateFilterLogicProps = {
    key: string
    onChange?: (fromDate: string | null, toDate: string | null, explicitDate?: boolean) => void
    dateFrom?: Dayjs | string | null
    dateTo?: Dayjs | string | null
    dateOptions?: DateMappingOption[]
    isDateFormatted?: boolean
    isFixedDateMode?: boolean
    placeholder?: string
    allowTimePrecision?: boolean
}

export const CUSTOM_OPTION_KEY = 'Custom'
export const SELECT_FIXED_VALUE_PLACEHOLDER = 'Select a value'
export const NO_OVERRIDE_RANGE_PLACEHOLDER = 'No date range override'
export const CUSTOM_OPTION_DESCRIPTION = 'Use the original date ranges of insights'
