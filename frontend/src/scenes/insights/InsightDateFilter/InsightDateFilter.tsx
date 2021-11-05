import React from 'react'
import { useValues, useActions } from 'kea'
import { DateFilterProps, DateFilter } from 'lib/components/DateFilter/DateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'

export function InsightDateFilter(props: DateFilterProps): JSX.Element {
    const { filters } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)

    return (
        <DateFilter
            {...props}
            dateFrom={filters.date_from || undefined}
            dateTo={filters.date_to || undefined}
            onChange={(changedDateFrom, changedDateTo) => {
                setFilters({ ...filters, date_from: changedDateFrom, date_to: changedDateTo })
                props.onChange?.(changedDateFrom, changedDateTo)
            }}
        />
    )
}
