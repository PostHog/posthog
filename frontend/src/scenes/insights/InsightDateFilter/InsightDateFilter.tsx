import React from 'react'
import { useValues, useActions } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilterProps, DateFilter } from 'lib/components/DateFilter/DateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'

export function InsightDateFilter(props: DateFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        dates: { dateFrom, dateTo },
    } = useValues(insightDateFilterLogic(insightProps))
    const { setDates } = useActions(insightDateFilterLogic(insightProps))

    return (
        <DateFilter
            {...props}
            dateFrom={dateFrom ?? undefined}
            dateTo={dateTo ?? undefined}
            onChange={(changedDateFrom, changedDateTo) => {
                setDates(changedDateFrom, changedDateTo)
                props.onChange?.(changedDateFrom, changedDateTo)
            }}
        />
    )
}
