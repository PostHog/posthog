import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils'

import { EnrichedSegment, EnrichedSegmentKeyActions, SegmentOutcome, SessionSummary } from '~/types'

import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'

export function AISessionSummary({ personId }: { personId: string }): JSX.Element | null {
    const logic = notebookNodePersonFeedLogic({ personId })
    const { canSummarize, hasErrors, sessionIdsWithRecording, summarizingState, summaries } = useValues(logic)
    const { summarizeSessions } = useActions(logic)

    if (!canSummarize) {
        return null
    }

    const numSessionsWithRecording = sessionIdsWithRecording.length
    const numSummaries = Object.values(summaries).length

    const pluralizedSessions = pluralize(numSessionsWithRecording, 'session')
    const pluralizedAnalyzedSessions = pluralize(numSummaries, 'session')

    return (
        <>
            <div className="mb-4 p-4 bg-surface-secondary rounded border">
                {summarizingState === 'idle' && (
                    <div className="flex items-center justify-between">
                        {numSessionsWithRecording > 0 ? (
                            <AISummaryMessage
                                heading="AI Session Summary"
                                subheading={`Analyze ${pluralizedSessions} and identify patterns`}
                            />
                        ) : (
                            <AISummaryMessage
                                heading="AI Session Summary"
                                subheading="No sessions with recordings found"
                            />
                        )}
                        <LemonButton
                            type="primary"
                            icon={<IconSparkles />}
                            onClick={summarizeSessions}
                            disabledReason={
                                numSessionsWithRecording === 0 ? 'No sessions with recordings found' : undefined
                            }
                            data-attr="person-feed-summarize-sessions"
                        >
                            Summarize Sessions
                        </LemonButton>
                    </div>
                )}

                {summarizingState === 'loading' && (
                    <div className="mb-4">
                        <AISummaryMessage
                            heading="Generating AI Summary"
                            subheading={`${pluralizedAnalyzedSessions} analyzed out of ${pluralizedSessions}.`}
                        />
                        <LemonProgress percent={(numSummaries / numSessionsWithRecording) * 100} />
                    </div>
                )}

                {summarizingState === 'success' && (
                    <AISummaryMessage
                        heading="AI Summary is ready"
                        subheading={`${numSummaries} out of ${pluralizedSessions} analyzed.`}
                    />
                )}

                {(summarizingState === 'loading' || numSummaries > 0 || hasErrors) && (
                    <div className="space-y-2">
                        {sessionIdsWithRecording.map((sessionId) => {
                            const summary = summaries[sessionId]
                            if (summary === 'error') {
                                return <SessionSummaryErrorCard key={sessionId} sessionId={sessionId} />
                            }
                            return summary ? (
                                <SessionSummaryCard key={sessionId} sessionId={sessionId} summary={summary} />
                            ) : (
                                <SessionSummaryCardSkeleton key={sessionId} sessionId={sessionId} />
                            )
                        })}
                    </div>
                )}
            </div>
        </>
    )
}

function AISummaryMessage({ heading, subheading }: { heading: string; subheading: string }): JSX.Element {
    return (
        <div className="mb-2">
            <div>
                <h3 className="font-semibold mb-1">{heading}</h3>
                <div className="text-sm text-muted">{subheading}</div>
            </div>
        </div>
    )
}

interface SessionSummaryCardProps {
    sessionId: string
    summary: SessionSummary
}

const SessionSummaryCardSkeleton = ({ sessionId }: { sessionId: string }): JSX.Element => {
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

export const SessionSummaryErrorCard = ({ sessionId }: { sessionId: string }): JSX.Element => {
    return (
        <div className="border border-danger rounded bg-bg-light mb-2">
            <div className="py-3 px-3 flex gap-2">
                <div className="w-3" />
                <div className="flex items-center gap-2 mb-2">
                    <span className="text-base font-bold text-danger">✗</span>
                    <div className="font-mono text-xs text-muted">{sessionId}</div>
                    <span className="text-xs text-muted">•</span>
                    <span className="text-xs text-danger">Failed</span>
                </div>
            </div>
        </div>
    )
}

const SessionSummaryCard = ({ sessionId, summary }: SessionSummaryCardProps): JSX.Element => {
    const [isExpanded, setIsExpanded] = useState(false)

    const successIcon = summary?.session_outcome?.success ? '✓' : '○'
    const successColor = summary?.session_outcome?.success ? 'text-success' : 'text-muted'

    const totalSegments = summary?.segments?.length || 0
    const totalEvents = summary?.segments?.reduce((acc, seg) => acc + (seg.meta?.events_count || 0), 0) || 0
    const totalKeyActions = summary?.key_actions?.reduce((acc, ka) => acc + (ka.events?.length || 0), 0) || 0
    const totalDuration = summary?.segments?.reduce((acc, seg) => acc + (seg.meta?.duration || 0), 0) || 0

    return (
        <div className="border rounded bg-bg-light mb-2">
            <LemonButton
                onClick={() => setIsExpanded(!isExpanded)}
                icon={
                    <IconChevronRight
                        className={`w-3 h-3 opacity-80 transition-transform ${!isExpanded ? '' : 'rotate-90'}`}
                    />
                }
                className="w-full py-2 flex gap-2 hover:bg-surface-secondary transition-colors text-left"
            >
                <div className="flex-1 space-y-2">
                    <div className="flex items-center gap-2 text-xs text-muted">
                        <span className={`text-base font-bold ${successColor}`}>{successIcon}</span>
                        <span className="font-mono">{sessionId}</span>
                        <span>•</span>
                        <span>{pluralize(totalSegments, 'segment', 'segments')}</span>
                    </div>
                    <p className="text-sm">{summary?.session_outcome?.description}</p>
                    <div className="flex gap-4 text-xs text-muted pt-1">
                        <span>{pluralize(totalEvents, 'event', 'events')}</span>
                        <span>{pluralize(totalKeyActions, 'key action', 'key actions')}</span>
                        <span>{formatDuration(totalDuration)} duration</span>
                    </div>
                </div>
            </LemonButton>

            {isExpanded && summary.segments && summary.segments.length > 0 && (
                <div className="p-3 border-t space-y-3">
                    <h4 className="font-semibold text-sm">Session Journey</h4>
                    {summary.segments.map((segment, idx) => {
                        const segmentOutcome = summary.segment_outcomes?.find((so) => so.segment_index === idx)
                        const segmentKeyActions = summary.key_actions?.find((ka) => ka.segment_index === idx)
                        const hasFailures = (segment.meta?.failure_count || 0) > 0

                        return (
                            <SegmentCard
                                key={idx}
                                segment={segment}
                                outcome={segmentOutcome}
                                keyActions={segmentKeyActions}
                                hasFailures={hasFailures}
                            />
                        )
                    })}
                </div>
            )}
        </div>
    )
}

interface SegmentCardProps {
    segment: EnrichedSegment
    outcome?: SegmentOutcome
    keyActions?: EnrichedSegmentKeyActions
    hasFailures: boolean
}

const SegmentCard = ({ segment, outcome, keyActions, hasFailures }: SegmentCardProps): JSX.Element => {
    const [isExpanded, setIsExpanded] = useState(false)

    const successIcon = outcome?.success ? '✓' : hasFailures ? '✗' : '○'
    const successColor = outcome?.success ? 'text-success' : hasFailures ? 'text-danger' : 'text-muted'

    return (
        <div className="border rounded bg-bg-3000 p-2">
            <div className="flex items-start gap-2">
                <span className={`text-sm font-bold ${successColor} mt-0.5`}>{successIcon}</span>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-sm">{segment.name}</span>
                        {hasFailures && (
                            <span className="text-xs text-danger bg-danger-highlight px-1.5 py-0.5 rounded">
                                {segment.meta?.failure_count} {pluralize(segment.meta?.failure_count || 0, 'issue')}
                            </span>
                        )}
                    </div>

                    {outcome?.summary && <p className="text-xs text-muted mb-2">{outcome.summary}</p>}

                    <div className="flex gap-3 text-xs text-muted mb-2">
                        <span>{segment.meta?.events_count || 0} events</span>
                        <span>{keyActions?.events?.length || 0} key actions</span>
                        <span>{formatDuration(segment.meta?.duration || 0)}</span>
                    </div>

                    {keyActions && keyActions.events && keyActions.events.length > 0 && (
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => setIsExpanded(!isExpanded)}
                            icon={
                                <IconChevronRight
                                    className={`w-3 h-3 transition-transform ${!isExpanded ? '' : 'rotate-90'}`}
                                />
                            }
                        >
                            {isExpanded ? 'Hide' : 'Show'} key actions
                        </LemonButton>
                    )}

                    {isExpanded && keyActions?.events && (
                        <div className="mt-2 space-y-1.5 pl-2 border-l-2 border-border">
                            {keyActions.events.map((action, idx) => (
                                <div key={idx} className="text-xs">
                                    <div className="flex items-start gap-1.5">
                                        {action.exception ? (
                                            <span className="text-danger">⚠</span>
                                        ) : action.confusion ? (
                                            <span className="text-warning">?</span>
                                        ) : action.abandonment ? (
                                            <span className="text-muted">⊗</span>
                                        ) : (
                                            <span className="text-muted">•</span>
                                        )}
                                        <div className="flex-1">
                                            <span className="text-default">{action.description}</span>
                                            {action.event && <span className="text-muted ml-1">({action.event})</span>}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

function formatDuration(seconds: number): string {
    if (seconds < 60) {
        return `${seconds}s`
    }
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    if (remainingSeconds === 0) {
        return `${minutes}m`
    }
    return `${minutes}m ${remainingSeconds}s`
}
