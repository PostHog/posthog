import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCalendar } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dateMapping } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

type InsightDateFilterProps = {
    disabled: boolean
}

export function InsightDateFilter({ disabled }: InsightDateFilterProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { isTrends, dateRange } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange } = useActions(insightVizDataLogic(insightProps))

    // Modify date options based on feature flags
    const dateOptions = useMemo(() => {
        return dateMapping.map((option) => {
            // If "Since event first seen" and feature flag is enabled, set inactive to false
            if (option.key === 'Since event first seen' && !!featureFlags[FEATURE_FLAGS.SINCE_EVENT_FIRST_SEEN]) {
                return { ...option, inactive: false }
            }
            return option
        })
    }, [featureFlags])

    return (
        <DateFilter
            dateTo={dateRange?.date_to ?? undefined}
            dateFrom={dateRange?.date_from ?? '-7d'}
            allowTimePrecision
            disabled={disabled}
            disabledReason={editingDisabledReason}
            onChange={(date_from, date_to, explicit_date) => {
                updateDateRange({ date_from, date_to, explicitDate: explicit_date })
            }}
            dateOptions={dateOptions}
            allowedRollingDateOptions={isTrends ? ['hours', 'days', 'weeks', 'months', 'years'] : undefined}
            makeLabel={(key) => (
                <>
                    <IconCalendar /> {key}
                </>
            )}
        />
    )
}
