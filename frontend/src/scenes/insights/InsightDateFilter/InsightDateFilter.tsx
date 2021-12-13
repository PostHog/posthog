import React from 'react'
import { useValues, useActions } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilterProps, DateFilter } from 'lib/components/DateFilter/DateFilter'
import './index.scss'

export function InsightDateFilter(props: DateFilterProps): JSX.Element {
    const logic = insightDateFilterLogic({ dateFrom: props.dateFrom, dateTo: props.dateTo })
    const {
        dates: { dateFrom, dateTo },
        highlightDateChange,
    } = useValues(logic)
    const { setDates } = useActions(logic)

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
