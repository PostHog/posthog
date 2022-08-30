import { Dayjs } from 'lib/dayjs'
import { DateMappingOption } from '~/types'

export enum DateFilterView {
    QuickList = 'QuickList',
    DateToNow = 'DateToNow',
    FixedRange = 'FixedRange',
}

export type DateFilterLogicProps = {
    key: string
    defaultValue: string
    onChange?: (fromDate: string, toDate: string | null) => void
    dateFrom?: Dayjs | string | null
    dateTo?: Dayjs | string | null
    dateOptions?: DateMappingOption[]
    isDateFormatted?: boolean
}
