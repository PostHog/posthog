import { useActions, useValues } from 'kea'

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
    const { isTrends, dateRange } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange } = useActions(insightVizDataLogic(insightProps))
    const { insightData } = useValues(insightVizDataLogic(insightProps))

    const { featureFlags } = useValues(featureFlagLogic)
    const canAccessExplicitDateToggle = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DATE_PICKER_EXPLICIT_DATE_TOGGLE]

    return (
        <DateFilter
            showExplicitDateToggle={canAccessExplicitDateToggle}
            dateTo={dateRange?.date_to ?? undefined}
            dateFrom={dateRange?.date_from ?? '-7d'}
            explicitDate={dateRange?.explicitDate ?? false}
            allowTimePrecision
            allowFixedRangeWithTime
            disabled={disabled}
            disabledReason={editingDisabledReason}
            onChange={(date_from, date_to, explicit_date) => {
                // Prevent debouncing when toggling the exact time range toggle as it glitches the animation
                const ignoreDebounce = dateRange?.explicitDate !== explicit_date
                updateDateRange({ date_from, date_to, explicitDate: explicit_date }, ignoreDebounce)
            }}
            dateOptions={dateMapping}
            allowedRollingDateOptions={isTrends ? ['hours', 'days', 'weeks', 'months', 'years'] : undefined}
            resolvedDateRange={insightData?.resolved_date_range}
            makeLabel={(key) => (
                <>
                    <IconCalendar /> {key}
                </>
            )}
        />
    )
}
