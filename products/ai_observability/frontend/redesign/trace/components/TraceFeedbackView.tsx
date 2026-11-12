import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import type { TraceFeedbackApi } from '../../../generated/api.schemas'
import { FeedbackStepContext } from '../types'
import { ErrorCallout } from './ErrorCallout'
import { FeedbackEmptyState } from './FeedbackEmptyState'
import { FeedbackScoresTable } from './FeedbackScoresTable'
import { FeedbackSurveyCard } from './FeedbackSurveyCard'
import { FeedbackTextCard } from './FeedbackTextCard'
import { UnansweredSurveyRow } from './UnansweredSurveyRow'

export interface TraceFeedbackViewProps {
    /** Null until the feedback has loaded. */
    feedback: TraceFeedbackApi | null
    failed: boolean
    steps: FeedbackStepContext
    onSelectStep: (nodeId: string) => void
    onRetry?: () => void
}

function firstFocusedEntryId({ scores, responses }: TraceFeedbackApi, focusNodeId: string | null): string | null {
    return [...scores, ...responses].find((entry) => entry.nodeId === focusNodeId)?.id ?? null
}

export function TraceFeedbackView({
    feedback,
    failed,
    steps,
    onSelectStep,
    onRetry,
}: TraceFeedbackViewProps): JSX.Element {
    if (failed) {
        return <ErrorCallout message="Feedback couldn't load." onRetry={onRetry} />
    }
    if (!feedback) {
        return <LemonSkeleton repeat={3} className="h-8" />
    }
    const scrollTargetId = firstFocusedEntryId(feedback, steps.focusNodeId)
    const surveysFailedBanner =
        feedback.surveyResponsesStatus === 'failed' ? (
            <LemonBanner type="warning" action={onRetry ? { children: 'Try again', onClick: onRetry } : undefined}>
                Survey responses couldn't load, so only the feedback your code sent shows here.
            </LemonBanner>
        ) : null
    if (feedback.scores.length === 0 && feedback.responses.length === 0 && feedback.unanswered.length === 0) {
        return (
            <div className="flex flex-col gap-4">
                {surveysFailedBanner}
                <FeedbackEmptyState />
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-4" data-attr="trace-view-feedback">
            {surveysFailedBanner}
            {feedback.scores.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <h3 className="m-0 text-sm font-semibold">Scores</h3>
                    <FeedbackScoresTable
                        scores={feedback.scores}
                        steps={steps}
                        onSelectStep={onSelectStep}
                        scrollTargetId={scrollTargetId}
                    />
                </section>
            ) : null}
            {feedback.responses.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <h3 className="m-0 text-sm font-semibold">What users said</h3>
                    <ul className="m-0 list-none divide-y divide-primary rounded border border-primary bg-surface-primary p-0">
                        {feedback.responses.map((item) =>
                            item.kind === 'text' ? (
                                <FeedbackTextCard
                                    key={`text-${item.id}`}
                                    item={item}
                                    steps={steps}
                                    onSelectStep={onSelectStep}
                                    isScrollTarget={item.id === scrollTargetId}
                                />
                            ) : (
                                <FeedbackSurveyCard
                                    key={`survey-${item.id}`}
                                    response={item}
                                    focused={item.nodeId === steps.focusNodeId}
                                    isScrollTarget={item.id === scrollTargetId}
                                />
                            )
                        )}
                    </ul>
                </section>
            ) : null}
            {feedback.unanswered.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <h3 className="m-0 text-sm font-semibold">Shown, not answered</h3>
                    <ul className="m-0 list-none divide-y divide-primary rounded border border-primary p-0">
                        {feedback.unanswered.map((item) => (
                            <UnansweredSurveyRow key={item.survey.id} item={item} />
                        ))}
                    </ul>
                </section>
            ) : null}
        </div>
    )
}
