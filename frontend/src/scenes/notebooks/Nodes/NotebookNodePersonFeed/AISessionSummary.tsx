import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'

import { EnrichedSessionGroupSummaryPattern } from '~/types'

import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'

export function AISessionSummary({ personId }: { personId: string }): JSX.Element | null {
    const logic = notebookNodePersonFeedLogic({ personId })
    const { canSummarize, sessionIdsWithRecording, sessionSummary, sessionSummaryLoading, summarizingState } =
        useValues(logic)
    const { summarizeSessions } = useActions(logic)

    if (!canSummarize) {
        return null
    }

    const numSessionsWithRecording = sessionIdsWithRecording.length

    const pluralizedSessions = pluralize(numSessionsWithRecording, 'session')

    return (
        <>
            <div className="mb-4 p-4 bg-surface-secondary rounded border">
                {!sessionSummary && summarizingState === 'idle' && (
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
                            loading={sessionSummaryLoading}
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
                    <AISummaryMessage
                        heading="Generating AI Summary"
                        subheading={`This may take 1-5 minutes. Analyzing ${pluralizedSessions} for patterns and insights.`}
                    />
                )}

                {sessionSummary && summarizingState === 'success' && (
                    <div className="space-y-2">
                        <AISummaryMessage
                            heading="Summary Results"
                            subheading="Summary generated successfully! Patterns are displayed below."
                        />
                        <p className="text-sm text-muted">
                            {pluralize(sessionSummary.patterns?.length || 0, 'pattern')} found
                        </p>
                        {sessionSummary.patterns.map((pattern: EnrichedSessionGroupSummaryPattern) => (
                            <PatternCard key={pattern.pattern_id} pattern={pattern} />
                        ))}
                    </div>
                )}

                {summarizingState === 'error' && (
                    <AISummaryMessage
                        heading="Error Generating Summary"
                        subheading="An error occurred while generating the summary. Please try again."
                    />
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

const severityColors: Record<string, string> = {
    critical: 'text-danger',
    high: 'text-warning',
    medium: 'text-muted',
    low: 'text-success',
}

const severityIcons: Record<string, string> = {
    critical: '🔴',
    high: '🟠',
    medium: '🟡',
    low: '🟢',
}

const PatternCard = ({ pattern }: { pattern: EnrichedSessionGroupSummaryPattern }): JSX.Element => {
    const [isExpanded, setIsExpanded] = useState(false)
    const severityIcon = severityIcons[pattern.severity] || '⚪'
    const severityColor = severityColors[pattern.severity] || 'text-muted'

    const sessionsAffectedPercent = (pattern.stats.sessions_affected_ratio * 100).toFixed(0)
    const successRate = (pattern.stats.segments_success_ratio * 100).toFixed(0)

    return (
        <div className="border rounded bg-bg-light mb-2">
            <LemonButton
                onClick={() => setIsExpanded(!isExpanded)}
                icon={
                    <IconChevronRight
                        className={`w-3 h-3 opacity-80 transition-transform ${!isExpanded ? '' : 'rotate-90'}`}
                    />
                }
                className="w-full py-3 flex gap-2 hover:bg-surface-secondary transition-colors text-left"
            >
                <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="text-base">{severityIcon}</span>
                        <span className="font-semibold">{pattern.pattern_name}</span>
                        <span className={`text-xs ${severityColor} uppercase`}>{pattern.severity}</span>
                    </div>
                    <p className="text-sm text-muted">{pattern.pattern_description}</p>
                    <div className="flex gap-4 mt-2 text-xs text-muted">
                        <span>
                            <strong>{sessionsAffectedPercent}%</strong> sessions affected
                        </span>
                        <span>
                            <strong>{successRate}%</strong> success rate
                        </span>
                        <span>
                            <strong>{pattern.stats.occurences}</strong> occurrences
                        </span>
                    </div>
                </div>
            </LemonButton>

            {isExpanded && (
                <div className="p-3 border-t">
                    <div className="ml-6">
                        <div className="mb-2">
                            <h4 className="font-semibold text-sm mb-1">Detection Indicators</h4>
                            <ul className="list-disc list-inside text-sm space-y-1">
                                {pattern.indicators.map((indicator, idx) => (
                                    <li key={idx} className="text-muted">
                                        {indicator}
                                    </li>
                                ))}
                            </ul>
                        </div>

                        {pattern.events.length > 0 && (
                            <div className="text-xs text-muted">
                                {pluralize(pattern.events.length, 'example')} available
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
