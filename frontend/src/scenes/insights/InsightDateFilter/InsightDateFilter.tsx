import React from 'react'
import { useActions, useValues } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilterProps, DateFilter } from 'lib/components/DateFilter/DateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'

export function InsightDateFilter(props: DateFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = insightDateFilterLogic(insightProps)
    const {
        dates: { dateFrom, dateTo },
        fallbackDateRange,
    } = useValues(logic)
    const { setDates } = useActions(logic)

    return (
        <span>
            <DateFilter
                {...props}
                fallbackValue={fallbackDateRange.fallback}
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
