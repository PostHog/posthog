import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    daysOfWeekLabel,
    getEffectiveDaysOfWeek,
} from 'scenes/insights/filters/InsightDateFilter/daysOfWeekFilterUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ComputationTimeWithRefresh } from './ComputationTimeWithRefresh'

type InsightResultMetadataProps = {
    disableLastComputation?: boolean
    disableLastComputationRefresh?: boolean
}

export const InsightResultMetadata = ({
    disableLastComputation,
    disableLastComputationRefresh,
}: InsightResultMetadataProps): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { samplingFactor, trendsFilter, dateRange } = useValues(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    // effectiveDays maps legacy hideWeekends→WEEKDAYS, unifying both paths.
    const effectiveDays = getEffectiveDaysOfWeek(dateRange, trendsFilter)
    // Show the pill for active daysOfWeek, or when the legacy flag is on and hideWeekends is set.
    const showDaysPill =
        (dateRange?.daysOfWeek && dateRange.daysOfWeek.length > 0) ||
        (trendsFilter?.hideWeekends && featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HIDE_WEEKENDS])
    return (
        <>
            {!disableLastComputation && <ComputationTimeWithRefresh disableRefresh={disableLastComputationRefresh} />}
            {samplingFactor ? (
                <span className="text-secondary">
                    {!disableLastComputation && <span className="mx-1">•</span>}
                    Results calculated from {samplingFactor * 100}% of users
                </span>
            ) : null}
            {showDaysPill ? (
                <span className="text-secondary">
                    <span className="mx-1">•</span>
                    {daysOfWeekLabel(effectiveDays)} only
                </span>
            ) : null}
        </>
    )
}
