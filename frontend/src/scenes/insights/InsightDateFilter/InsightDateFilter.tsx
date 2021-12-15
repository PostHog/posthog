import React from 'react'
import { useActions, useValues } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilterProps, DateFilter } from 'lib/components/DateFilter/DateFilter'
import './index.scss'
import { insightLogic } from 'scenes/insights/insightLogic'

export function InsightDateFilter(props: DateFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)
    const logic = insightDateFilterLogic(insightProps)
    const {
        dates: { dateFrom, dateTo },
        highlightDateChange,
        fallbackDateRange,
    } = useValues(logic)

    return (
        <span className={highlightDateChange ? 'insights-date-filter highlighted' : ''}>
            <DateFilter
                {...props}
                fallbackValue={fallbackDateRange.fallback}
                dateFrom={dateFrom}
                dateTo={dateTo}
                onChange={(changedDateFrom, changedDateTo) => {
                    setFilters({ date_from: changedDateFrom, date_to: changedDateTo })
                    props.onChange?.(changedDateFrom, changedDateTo)
                }}
            />
        </span>
    )
}
