import { useValues } from 'kea'

import {
    daysOfWeekLabel,
    getExcludedDaysOfWeek,
    querySupportsDaysOfWeek,
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
    const { samplingFactor, dateRange, querySource } = useValues(insightVizDataLogic(insightProps))

    // Only insights that apply daysOfWeek server-side get the note
    const excludedDays = querySupportsDaysOfWeek(querySource) ? getExcludedDaysOfWeek(dateRange) : []
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
            {excludedDays.length > 0 ? (
                <span className="text-secondary">
                    <span className="mx-1">•</span>
                    Excluding {excludedText}
                </span>
            ) : null}
            {dateRange?.excludeIncompletePeriods ? (
                <span className="text-secondary">
                    <span className="mx-1">•</span>
                    Incomplete periods excluded
                </span>
            ) : null}
        </>
    )
}
