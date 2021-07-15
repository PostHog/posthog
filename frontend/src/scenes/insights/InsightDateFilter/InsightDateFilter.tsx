import React from 'react'
import { useValues, useActions } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilterProps, DateFilter } from 'lib/components/DateFilter/DateFilter'
import './index.scss'

export function InsightDateFilter(props: DateFilterProps): JSX.Element {
    const {
        dates: { dateFrom, dateTo },
        highlightDateChange,
    } = useValues(insightDateFilterLogic)
    const { setDates } = useActions(insightDateFilterLogic)

    return (
        <span className={highlightDateChange ? 'insights-date-filter highlighted' : ''}>
            <DateFilter
                {...props}
                dateFrom={dateFrom}
                dateTo={dateTo}
                onChange={(changedDateFrom, changedDateTo) => {
                    setDates(changedDateFrom, changedDateTo)
                    props.onChange?.(changedDateFrom, changedDateTo)
                }}
            />
        </span>
    )
}
