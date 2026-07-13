import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    ALL_DAY_NUMBERS,
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

    const composerEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_DATE_COMPOSER]
    const includedDays = getEffectiveDaysOfWeek(dateRange, trendsFilter)
    const excludedDays = includedDays.length === 0 ? [] : ALL_DAY_NUMBERS.filter((day) => !includedDays.includes(day))
    const excludedLabel = daysOfWeekLabel(excludedDays)
    const excludedText = ['Weekends', 'Weekdays'].includes(excludedLabel) ? excludedLabel.toLowerCase() : excludedLabel

    return (
        <>
            {!disableLastComputation && <ComputationTimeWithRefresh disableRefresh={disableLastComputationRefresh} />}
            {samplingFactor ? (
                <span className="text-secondary">
                    {!disableLastComputation && <span className="mx-1">•</span>}
                    Results calculated from {samplingFactor * 100}% of users
                </span>
            ) : null}
            {composerEnabled && excludedDays.length > 0 ? (
                <span className="text-secondary">
                    <span className="mx-1">•</span>
                    Excluding {excludedText}
                </span>
            ) : !composerEnabled &&
              trendsFilter?.hideWeekends &&
              featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HIDE_WEEKENDS] ? (
                <span className="text-secondary">
                    <span className="mx-1">•</span>
                    Weekends hidden
                </span>
            ) : null}
            {composerEnabled && dateRange?.excludeIncompletePeriods ? (
                <span className="text-secondary">
                    <span className="mx-1">•</span>
                    Incomplete period excluded
                </span>
            ) : null}
        </>
    )
}
