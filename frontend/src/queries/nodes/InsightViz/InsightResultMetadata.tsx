import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    DAYS_IN_WEEK,
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
    const effectiveDays = getEffectiveDaysOfWeek(dateRange, trendsFilter)
    const daysRestrict = effectiveDays.length > 0 && effectiveDays.length < DAYS_IN_WEEK
    const showDaysPill =
        daysRestrict &&
        ((dateRange?.daysOfWeek && dateRange.daysOfWeek.length > 0) ||
            (trendsFilter?.hideWeekends && featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HIDE_WEEKENDS]))
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
