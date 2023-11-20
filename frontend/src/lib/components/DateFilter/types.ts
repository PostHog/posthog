import { Dayjs } from 'lib/dayjs'

import { DateMappingOption } from '~/types'

export enum DateFilterView {
    QuickList = 'QuickList',
    DateToNow = 'DateToNow',
    FixedRange = 'FixedRange',
}

export type DateFilterLogicProps = {
    key: string
    onChange?: (fromDate: string | null, toDate: string | null) => void
    dateFrom?: Dayjs | string | null
    dateTo?: Dayjs | string | null
    dateOptions?: DateMappingOption[]
    isDateFormatted?: boolean
}

export const CUSTOM_OPTION_KEY = 'Custom'
export const CUSTOM_OPTION_VALUE = 'No date range override'
export const CUSTOM_OPTION_DESCRIPTION = 'Use the original date ranges of insights'
