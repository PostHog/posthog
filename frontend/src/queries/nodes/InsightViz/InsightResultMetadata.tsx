import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import {
    daysOfWeekLabel,
    getExcludedDaysOfWeek,
    querySupportsDaysOfWeek,
} from '~/queries/nodes/InsightViz/daysOfWeekFilterUtils'

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
    const quillSurface = useQuillSurface()
    // Inside quill the wrapping Text sets the color, so the notes drop the Lemon one.
    const noteClassName = quillSurface ? undefined : 'text-secondary'

    // Only insights that apply daysOfWeek server-side get the note
    const excludedDays = querySupportsDaysOfWeek(querySource) ? getExcludedDaysOfWeek(dateRange) : []
    const excludedLabel = daysOfWeekLabel(excludedDays)
    const excludedText = ['Weekends', 'Weekdays'].includes(excludedLabel) ? excludedLabel.toLowerCase() : excludedLabel

    const metadata = (
        <>
            {!disableLastComputation && <ComputationTimeWithRefresh disableRefresh={disableLastComputationRefresh} />}
            {samplingFactor ? (
                <span className={noteClassName}>
                    {!disableLastComputation && <span className="mx-1">•</span>}
                    Results calculated from {samplingFactor * 100}% of users
                </span>
            ) : null}
            {excludedDays.length > 0 ? (
                <span className={noteClassName}>
                    <span className="mx-1">•</span>
                    Excluding {excludedText}
                </span>
            ) : null}
            {dateRange?.excludeIncompletePeriods ? (
                <span className={noteClassName}>
                    <span className="mx-1">•</span>
                    Incomplete periods excluded
                </span>
            ) : null}
        </>
    )

    return quillSurface ? (
        <Text size="xs" variant="muted" render={<div className="m-0 flex flex-wrap items-center gap-x-2" />}>
            {metadata}
        </Text>
    ) : (
        metadata
    )
}
