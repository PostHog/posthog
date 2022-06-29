import React from 'react'
import { useValues, useActions } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilterExperiment } from 'lib/components/DateFilter/DateFilterExperiment'
import { DateFilterProps, DateFilter } from 'lib/components/DateFilter/DateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function InsightDateFilter(props: DateFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        dates: { dateFrom, dateTo },
    } = useValues(insightDateFilterLogic(insightProps))
    const { setDates } = useActions(insightDateFilterLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const dateFilterExperiment = !!featureFlags[FEATURE_FLAGS.DATE_FILTER_EXPERIMENT]

    return dateFilterExperiment ? (
        <DateFilterExperiment
            {...props}
            dateFrom={dateFrom ?? undefined}
            dateTo={dateTo ?? undefined}
            onChange={(changedDateFrom, changedDateTo) => {
                setDates(changedDateFrom, changedDateTo)
                props.onChange?.(changedDateFrom, changedDateTo)
            }}
        />
    ) : (
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
