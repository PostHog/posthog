import React from 'react'
import { useValues, useActions } from 'kea'
import { dateFilterLogic } from './dateFilterLogic'
import { DateFilterProps, DateFilter as DateFilterComponent } from 'lib/components/DateFilter/DateFilter'

export function DateFilter(props: DateFilterProps): JSX.Element {
    const {
        dates: { dateFrom, dateTo },
    } = useValues(dateFilterLogic)
    const { setDates } = useActions(dateFilterLogic)

    return (
        <DateFilterComponent
            {...props}
            dateFrom={dateFrom}
            dateTo={dateTo}
            onChange={(dateFrom, dateTo) => {
                setDates(dateFrom, dateTo)
                props.onChange?.(dateFrom, dateTo)
            }}
        />
    )
}
