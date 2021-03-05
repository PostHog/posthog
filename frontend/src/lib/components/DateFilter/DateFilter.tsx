import React from 'react'
import { useValues, useActions } from 'kea'
import { dateFilterLogic } from './dateFilterLogic'
import { DateFilterProps, DateFilterComponent } from 'lib/components/DateFilter/DateFilterComponent'

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
                setDates(dateFrom, dateTo, true)
                props.onChange?.(dateFrom, dateTo)
            }}
        />
    )
}
