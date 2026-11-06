import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { FeedbackModeState } from '../types'
import { ErrorCallout } from './ErrorCallout'
import { FeedbackEmptyState } from './FeedbackEmptyState'
import { FeedbackScoresTable } from './FeedbackScoresTable'
import { FeedbackSurveyCard } from './FeedbackSurveyCard'
import { FeedbackTextCard } from './FeedbackTextCard'
import { UnansweredSurveyRow } from './UnansweredSurveyRow'

export interface TraceFeedbackViewProps {
    state: FeedbackModeState
    onSelectStep: (nodeId: string) => void
    onRetry?: () => void
}

function firstFocusedEntryId(state: FeedbackModeState): string | null {
    if (state.status !== 'ready') {
        return null
    }
    return [...state.scores, ...state.responses].find((entry) => entry.focused)?.id ?? null
}

export function TraceFeedbackView({ state, onSelectStep, onRetry }: TraceFeedbackViewProps): JSX.Element {
    const scrollTargetId = firstFocusedEntryId(state)
    if (state.status === 'loading') {
        return <LemonSkeleton repeat={3} className="h-8" />
    }
    if (state.status === 'error') {
        return <ErrorCallout message="Feedback couldn't load." onRetry={onRetry} />
    }
    const surveysFailedBanner = state.surveysFailed ? (
        <LemonBanner type="warning" action={onRetry ? { children: 'Try again', onClick: onRetry } : undefined}>
            Survey responses couldn't load, so only the feedback your code sent shows here.
        </LemonBanner>
    ) : null
    if (state.scores.length === 0 && state.responses.length === 0 && state.unanswered.length === 0) {
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
            {state.scores.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <h3 className="m-0 text-sm font-semibold">Scores</h3>
                    <FeedbackScoresTable
                        scores={state.scores}
                        onSelectStep={onSelectStep}
                        scrollTargetId={scrollTargetId}
                    />
                </section>
            ) : null}
            {state.responses.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <h3 className="m-0 text-sm font-semibold">What users said</h3>
                    <ul className="m-0 list-none divide-y divide-primary rounded border border-primary bg-surface-primary p-0">
                        {state.responses.map((item) =>
                            item.kind === 'text' ? (
                                <FeedbackTextCard
                                    key={`text-${item.id}`}
                                    item={item}
                                    onSelectStep={onSelectStep}
                                    isScrollTarget={item.id === scrollTargetId}
                                />
                            ) : (
                                <FeedbackSurveyCard
                                    key={`survey-${item.id}`}
                                    response={item}
                                    isScrollTarget={item.id === scrollTargetId}
                                />
                            )
                        )}
                    </ul>
                </section>
            ) : null}
            {state.unanswered.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <h3 className="m-0 text-sm font-semibold">Shown, not answered</h3>
                    <ul className="m-0 list-none divide-y divide-primary rounded border border-primary p-0">
                        {state.unanswered.map((item) => (
                            <UnansweredSurveyRow key={item.survey.id} item={item} />
                        ))}
                    </ul>
                </section>
            ) : null}
        </div>
    )
}
