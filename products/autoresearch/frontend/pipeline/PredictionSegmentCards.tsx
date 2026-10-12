import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { PredictionSegmentDefinition, formatProbability, predictionSegmentPeopleUrl } from '../predictionSegments'

function SegmentCard({ segment }: { segment: PredictionSegmentDefinition }): JSX.Element {
    const { pipeline, predictionSegments, savingCohortSegment, segmentThresholds } =
        useValues(autoresearchPipelineLogic)
    const { saveSegmentCohort } = useActions(autoresearchPipelineLogic)

    const stats = predictionSegments?.[segment.key]
    const totalPeople = predictionSegments
        ? Object.values(predictionSegments).reduce((sum, { people }) => sum + people, 0)
        : 0
    const share = stats && totalPeople > 0 ? (100 * stats.people) / totalPeople : 0
    const outputProperty = pipeline?.output_person_property ?? ''

    return (
        <div className="flex-1 min-w-60 border rounded p-4 flex flex-col gap-2 bg-surface-primary">
            <div className="flex items-center gap-2">
                <span className={`size-2.5 rounded-full shrink-0 ${segment.colorClassName}`} />
                <span className="font-semibold">{segment.label}</span>
                <span className="text-xs text-muted">{segment.range}</span>
            </div>
            {stats ? (
                <>
                    <div className="text-2xl font-semibold tabular-nums">
                        {stats.people.toLocaleString()}{' '}
                        <span className="text-sm font-normal text-muted">people ({share.toFixed(1)}%)</span>
                    </div>
                    <Tooltip title="The sum of this segment's predicted probabilities">
                        <span className="text-sm text-secondary">
                            About {humanFriendlyNumber(Math.round(stats.expectedConversions))} expected to convert
                            {pipeline?.horizon_days ? ` within ${pipeline.horizon_days} days` : ''}
                        </span>
                    </Tooltip>
                </>
            ) : (
                <LemonSkeleton className="h-12" />
            )}
            <div className="flex flex-wrap gap-2 mt-auto pt-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    data-attr={`autoresearch-segment-save-cohort-${segment.key}`}
                    loading={savingCohortSegment === segment.key}
                    disabledReason={
                        !stats
                            ? 'Segments are still loading'
                            : savingCohortSegment
                              ? 'A cohort is being saved'
                              : undefined
                    }
                    onClick={() => saveSegmentCohort(segment.key)}
                >
                    Save as cohort
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    data-attr={`autoresearch-segment-view-people-${segment.key}`}
                    to={
                        segmentThresholds
                            ? predictionSegmentPeopleUrl(segment.key, outputProperty, segmentThresholds)
                            : undefined
                    }
                    disabledReason={
                        !outputProperty
                            ? 'The model has no output property'
                            : !segmentThresholds
                              ? 'Segments are still loading'
                              : undefined
                    }
                >
                    View people
                </LemonButton>
            </div>
        </div>
    )
}

function SegmentCutPoints(): JSX.Element | null {
    const { pipeline, segmentThresholds: thresholds } = useValues(autoresearchPipelineLogic)
    if (!thresholds) {
        return null
    }
    const target = pipeline?.target_event ?? 'the target event'
    return (
        <>
            <p className="text-sm text-secondary mb-0">
                {thresholds.base_rate != null
                    ? `Segments compare each score with the average: ${formatProbability(thresholds.base_rate)} of scored people did ${target} over the last ${thresholds.base_rate_dates} checked dates.`
                    : 'Segments use fixed cut points until enough predictions are checked against what people did.'}
            </p>
            {thresholds.scores_miscalibrated &&
                thresholds.champion_mean_p_y != null &&
                thresholds.champion_base_rate != null && (
                    <LemonBanner type="warning">
                        This model's scores are not true probabilities. It predicted{' '}
                        {formatProbability(thresholds.champion_mean_p_y)} on average, and{' '}
                        {formatProbability(thresholds.champion_base_rate)} of people did {target}. The segments still
                        rank people, but a score of {thresholds.likely_lift}× average may not mean{' '}
                        {thresholds.likely_lift}× as likely. Check the Accuracy tab before you act on the percentages.
                    </LemonBanner>
                )}
        </>
    )
}

export function PredictionSegmentCards(): JSX.Element {
    const { predictionSegmentsError, segmentDefinitions } = useValues(autoresearchPipelineLogic)

    if (predictionSegmentsError) {
        return <p className="text-sm text-muted mb-0">Couldn't load the segments. Refresh the page to try again.</p>
    }
    if (!segmentDefinitions) {
        return <LemonSkeleton className="h-40" />
    }
    return (
        <div className="space-y-3">
            <SegmentCutPoints />
            <div className="flex flex-wrap gap-4">
                {segmentDefinitions.map((segment) => (
                    <SegmentCard key={segment.key} segment={segment} />
                ))}
            </div>
        </div>
    )
}
