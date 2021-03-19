import React from 'react'
import { useValues, useActions } from 'kea'
import { dateFilterLogic } from './dateFilterLogic'
import { DateFilterProps, DateFilter as DateFilterComponent } from 'lib/components/DateFilter/DateFilter'

export function DateFilter(props: DateFilterProps): JSX.Element {
    const {
        dates: { dateFrom, dateTo },
        dateAutoChanged,
    } = useValues(dateFilterLogic)
    const { setDates } = useActions(dateFilterLogic)

    return (
        <span className={dateAutoChanged ? 'highlighted' : ''}>
            <DateFilterComponent
                {...props}
                dateFrom={dateFrom}
                dateTo={dateTo}
                onChange={(dateFrom, dateTo) => {
                    setDates(dateFrom, dateTo)
                    props.onChange?.(dateFrom, dateTo)
                }}
            />
        </span>
    )
}
