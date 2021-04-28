import React from 'react'
import { useValues, useActions } from 'kea'
import { dateFilterLogic } from './dateFilterLogic'
import { DateFilterProps, DateFilter as DateFilterComponent } from 'lib/components/DateFilter/DateFilter'
import './index.scss'

export function DateFilter(props: DateFilterProps): JSX.Element {
    const {
        dates: { dateFrom, dateTo },
        highlightDateChange,
    } = useValues(dateFilterLogic)
    const { setDates } = useActions(dateFilterLogic)

    return (
        <span className={highlightDateChange ? 'insights-date-filter highlighted' : ''}>
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
