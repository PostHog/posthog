import { BindLogic, useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils'

import { notebookNodePersonFeedLogic } from '../notebookNodePersonFeedLogic'
import { AISummaryMessage } from './AISummaryMessage'
import { SessionSummaryCard, SessionSummaryCardProps } from './SessionSummaryCard'
import { SessionSummaryErrorCard } from './SessionSummaryErrorCard'

export function AISessionSummary({ personId }: { personId: string }): JSX.Element | null {
    const logic = notebookNodePersonFeedLogic({ personId })
    const { canSummarize, numErrors, numSummaries, progressText, summarizingState } = useValues(logic)

    if (!canSummarize) {
        return null
    }

    return (
        <BindLogic logic={notebookNodePersonFeedLogic} props={{ personId }}>
            <div className="mb-4 p-4 bg-surface-secondary rounded border">
                {summarizingState === 'idle' && <AISummaryIdle />}
                {summarizingState === 'loading' && <AISummaryLoading />}
                {summarizingState === 'completed' && (
                    <AISummaryMessage heading="AI Summary is ready" subheading={progressText} />
                )}

                {(summarizingState === 'loading' || numSummaries > 0 || numErrors > 0) && <AISummaryResults />}
            </div>
        </BindLogic>
    )
}

function AISummaryIdle(): JSX.Element {
    const { numSessionsWithRecording } = useValues(notebookNodePersonFeedLogic)
    const { summarizeSessions } = useActions(notebookNodePersonFeedLogic)

    return (
        <div className="flex items-center justify-between">
            {numSessionsWithRecording > 0 ? (
                <AISummaryMessage
                    heading="AI Session Summary"
                    subheading={`Analyze ${pluralize(numSessionsWithRecording, 'session')} and identify patterns`}
                />
            ) : (
                <AISummaryMessage heading="AI Session Summary" subheading="No sessions with recordings found" />
            )}
            <LemonButton
                type="primary"
                icon={<IconSparkles />}
                onClick={summarizeSessions}
                disabledReason={numSessionsWithRecording === 0 ? 'No sessions with recordings found' : undefined}
                data-attr="person-feed-summarize-sessions"
            >
                Summarize Sessions
            </LemonButton>
        </div>
    )
}

function AISummaryLoading(): JSX.Element {
    const { numSessionsProcessed, numSessionsWithRecording, progressText } = useValues(notebookNodePersonFeedLogic)
    return (
        <div className="mb-4">
            <AISummaryMessage heading="Generating AI Summary" subheading={progressText} />
            <LemonProgress percent={(numSessionsProcessed / numSessionsWithRecording) * 100} />
        </div>
    )
}

function AISummaryResults(): JSX.Element {
    const { sessionIdsWithRecording, summaries, summarizingErrors } = useValues(notebookNodePersonFeedLogic)

    return (
        <div className="space-y-2">
            {sessionIdsWithRecording.map((sessionId) => {
                const summary = summaries[sessionId]
                if (summary) {
                    return <SessionSummaryCard key={sessionId} sessionId={sessionId} summary={summary} />
                }

                const error = summarizingErrors[sessionId]
                if (error) {
                    return <SessionSummaryErrorCard key={sessionId} sessionId={sessionId} errorMessage={error} />
                }

                return <SessionSummaryCardSkeleton key={sessionId} sessionId={sessionId} />
            })}
        </div>
    )
}

const SessionSummaryCardSkeleton = ({ sessionId }: Pick<SessionSummaryCardProps, 'sessionId'>): JSX.Element => {
    return (
        <div className="border rounded bg-bg-light mb-2 animate-pulse">
            <div className="py-3 px-3 flex gap-2">
                <div className="w-3" />
                <div className="flex flex-col flex-1">
                    <div className="flex items-center gap-2 mb-4">
                        <LemonSkeleton className="w-4 h-4" />
                        <span className="font-mono text-xs text-muted">{sessionId}</span>
                        <span className="text-xs text-muted">•</span>
                        <span className="text-xs text-muted">Loading...</span>
                    </div>
                    <LemonSkeleton className="h-4 w-3/4 mb-2" />
                    <div className="flex gap-4 mt-2">
                        <LemonSkeleton className="h-3 w-16" />
                        <LemonSkeleton className="h-3 w-20" />
                        <LemonSkeleton className="h-3 w-16" />
                    </div>
                </div>
            </div>
        </div>
    )
}
