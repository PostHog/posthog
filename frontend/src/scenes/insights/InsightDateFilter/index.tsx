import React from 'react'
import { useValues, useActions } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilterProps, DateFilter as DateFilterComponent } from 'lib/components/DateFilter/DateFilter'
import './index.scss'

export function InsightDateFilter(props: DateFilterProps): JSX.Element {
    const {
        dates: { dateFrom, dateTo },
        highlightDateChange,
    } = useValues(insightDateFilterLogic)
    const { setDates } = useActions(insightDateFilterLogic)

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
