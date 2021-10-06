import React from 'react'
import { useValues, useActions } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilterProps, DateFilter } from 'lib/components/DateFilter/DateFilter'
import './index.scss'
import { insightLogic } from 'scenes/insights/insightLogic'

export function InsightDateFilter(props: DateFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        dates: { dateFrom, dateTo },
        highlightDateChange,
    } = useValues(insightDateFilterLogic(insightProps))
    const { setDates } = useActions(insightDateFilterLogic(insightProps))

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
