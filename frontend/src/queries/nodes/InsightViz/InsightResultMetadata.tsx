import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { daysOfWeekLabel } from 'scenes/insights/EditorFilters/daysOfWeekFilterUtils'
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
    return (
        <>
            {!disableLastComputation && <ComputationTimeWithRefresh disableRefresh={disableLastComputationRefresh} />}
            {samplingFactor ? (
                <span className="text-secondary">
                    {!disableLastComputation && <span className="mx-1">•</span>}
                    Results calculated from {samplingFactor * 100}% of users
                </span>
            ) : null}
            {dateRange?.daysOfWeek?.length && dateRange.daysOfWeek.length < 7 ? (
                <span className="text-secondary">
                    <span className="mx-1">•</span>
                    {daysOfWeekLabel([...dateRange.daysOfWeek].sort((a, b) => a - b))} only
                </span>
            ) : trendsFilter?.hideWeekends && featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HIDE_WEEKENDS] ? (
                <span className="text-secondary">
                    <span className="mx-1">•</span>
                    Weekends hidden
                </span>
            ) : null}
        </>
    )
}
