import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconChevronDown, IconCopy, IconMagicWand, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { AllowTrainingCallout } from 'lib/components/AllowTrainingCallout/AllowTrainingCallout'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { playerMetaLogic } from './player-meta/playerMetaLogic'
import { sessionSummaryProgressLogic } from './player-meta/sessionSummaryProgressLogic'
import { SessionSummaryContent } from './player-meta/types'
import { LoadingTimer, SessionSummary, SummarizationProgressView } from './PlayerSummaryViews'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

const COLLAPSED_HEIGHT = 44
const DEFAULT_EXPANDED_HEIGHT = 480
const MIN_EXPANDED_HEIGHT = 120
const MAX_EXPANDED_HEIGHT = 800

function formatSessionSummary(summary: SessionSummaryContent, sessionId: string): string {
    const recordingUrl = window.location.origin + urls.replaySingle(sessionId)
    const lines: string[] = [`Session ID: ${sessionId}`, `Recording: ${recordingUrl}`, '']

    if (summary.session_outcome?.description) {
        const outcomeLabel = summary.session_outcome.success === false ? 'Failure' : 'Success'
        lines.push(`Outcome: ${outcomeLabel}`, summary.session_outcome.description, '')
    }

    summary.segments?.forEach((segment, i) => {
        lines.push(`${i + 1}. ${segment.name ?? 'Unnamed segment'}`)

        const segmentOutcome = summary.segment_outcomes?.find((o) => o.segment_index === segment.index)
        if (segmentOutcome) {
            const outcomeLabel = segmentOutcome.success === false ? 'Failure' : 'Success'
            lines.push(`   Outcome: ${outcomeLabel}`)
            if (segmentOutcome.summary) {
                lines.push(`   ${segmentOutcome.summary}`)
            }
        }

        const events = (summary.key_actions ?? [])
            .filter((k) => k.segment_index === segment.index)
            .flatMap((k) => k.events ?? [])
        if (events.length) {
            lines.push('   Key actions:')
            events.forEach((event) => {
                const parts: string[] = []
                if (event.description) {
                    parts.push(event.description)
                }
                if (event.event_type) {
                    parts.push(`[${event.event_type}]`)
                }
                if (event.current_url) {
                    parts.push(`@ ${event.current_url}`)
                }
                lines.push(`     - ${parts.join(' ')}`)
            })
        }
        lines.push('')
    })

    return lines.join('\n').trim()
}

export function PlayerSummaryDock(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { logicProps, sessionRecordingId, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const {
        sessionSummary,
        sessionSummaryLoading,
        summarizationProgress,
        sessionSummaryError,
        sessionSummaryHasRetried,
        summaryDisabledReason,
    } = useValues(playerMetaLogic(logicProps))
    const { summarizeSession } = useActions(playerMetaLogic(logicProps))
    const { openBySessionId, summaryIdBySessionId } = useValues(sessionSummaryProgressLogic)
    const { setSummaryOpen, cancelSummarization } = useActions(sessionSummaryProgressLogic)
    const { reportAISessionSummaryViewed, reportAISessionSummaryCopiedForLLM } = useActions(
        sessionRecordingEventUsageLogic
    )

    const dockRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        logicKey: 'player-summary-dock',
        placement: 'top',
        containerRef: dockRef,
    }
    const { desiredSize, isResizeInProgress } = useValues(resizerLogic(resizerProps))

    const isEnabled = featureFlags[FEATURE_FLAGS.REPLAY_VIDEO_BASED_SUMMARIZATION]
    const hasSummary = !!sessionSummary
    const isOpen = !!openBySessionId[sessionRecordingId]
    const summaryId = summaryIdBySessionId[sessionRecordingId] ?? null
    const hasRenderedSummary = hasSummary && !sessionSummaryError
    const setIsOpen = (open: boolean): void => setSummaryOpen(sessionRecordingId, open)
    // Cap the default height to the viewport so the dock can't crush the player.
    const expandedMaxHeight = desiredSize
        ? `${Math.max(MIN_EXPANDED_HEIGHT, Math.min(MAX_EXPANDED_HEIGHT, desiredSize))}px`
        : `min(${DEFAULT_EXPANDED_HEIGHT}px, 45vh)`

    // `isOpen` flips multiple times per summary, so dedupe to one capture per render.
    const capturedKeyRef = useRef<string | null>(null)

    useEffect(() => {
        if (!sessionRecordingId || !isOpen || !hasRenderedSummary) {
            return
        }
        const key = `${sessionRecordingId}|${summaryId ?? 'unknown'}`
        if (capturedKeyRef.current === key) {
            return
        }
        capturedKeyRef.current = key
        reportAISessionSummaryViewed(sessionRecordingId, 'dock', summaryId)
    }, [sessionRecordingId, isOpen, hasRenderedSummary, summaryId, reportAISessionSummaryViewed])

    if (!isEnabled) {
        return null
    }

    const hasContentToExpand = hasSummary || sessionSummaryLoading || !!sessionSummaryError

    return (
        <div
            ref={dockRef}
            className={clsx(
                'relative border-t bg-surface-primary overflow-hidden flex flex-col',
                !isResizeInProgress && 'transition-[max-height] duration-300 ease-out'
            )}
            style={{ maxHeight: isOpen ? expandedMaxHeight : COLLAPSED_HEIGHT }}
            data-attr="player-summary-dock"
        >
            {isOpen && <Resizer {...resizerProps} />}
            <div className="flex items-center justify-between h-11 px-3 shrink-0">
                {hasSummary ? (
                    <div className="flex items-center gap-2 font-semibold">
                        <IconMagicWand className="text-primary" />
                        AI summary
                    </div>
                ) : sessionSummaryLoading ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconX />}
                        onClick={() => cancelSummarization(sessionRecordingId)}
                        tooltip="Stop summarizing this session"
                        data-attr="cancel-session-summary"
                    >
                        Cancel summarization
                    </LemonButton>
                ) : !isCloudOrDev ? (
                    // AI session summaries run on PostHog Cloud only — show the standard upsell.
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconMagicWand />}
                        to={urls.moveToPostHogCloud()}
                        tooltip="AI session summaries are a PostHog Cloud feature (separate from PostHog AI, which runs on your own provider key)"
                        data-attr="session-summary-move-to-cloud"
                    >
                        Summarize with PostHog Cloud
                    </LemonButton>
                ) : (
                    <LemonButton
                        size="small"
                        type="primary"
                        icon={<IconMagicWand />}
                        disabledReason={summaryDisabledReason}
                        onClick={() => {
                            summarizeSession()
                            setIsOpen(true)
                        }}
                        data-attr="load-session-summary"
                    >
                        Use AI to summarize this session
                    </LemonButton>
                )}
                <div className="flex items-center gap-1">
                    {sessionSummary && (
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCopy />}
                            tooltip="Copy session summary for LLM"
                            aria-label="Copy session summary for LLM"
                            data-attr="copy-session-summary-for-llm"
                            onClick={async () => {
                                const success = await copyToClipboard(
                                    formatSessionSummary(sessionSummary, sessionRecordingId),
                                    'session summary'
                                )
                                if (!success) {
                                    return
                                }
                                reportAISessionSummaryCopiedForLLM(sessionRecordingId, {
                                    segment_count: sessionSummary.segments?.length ?? 0,
                                    key_action_count:
                                        sessionSummary.key_actions?.reduce(
                                            (sum, k) => sum + (k.events?.length ?? 0),
                                            0
                                        ) ?? 0,
                                    has_session_outcome: !!sessionSummary.session_outcome,
                                })
                            }}
                        >
                            Copy
                        </LemonButton>
                    )}
                    {(hasContentToExpand || isOpen) && (
                        <LemonButton
                            size="small"
                            icon={<IconChevronDown className={isOpen ? '' : 'rotate-180'} />}
                            onClick={() => setIsOpen(!isOpen)}
                            tooltip={isOpen ? 'Collapse' : 'Expand'}
                            aria-label={isOpen ? 'Collapse summary' : 'Expand summary'}
                        />
                    )}
                </div>
            </div>
            {isOpen && (
                <div className="flex-1 overflow-y-auto px-3 pb-3">
                    <AllowTrainingCallout featureName="session summaries" />
                    {sessionSummaryLoading ? (
                        <>
                            {sessionSummaryHasRetried && (
                                <LemonBanner type="warning" className="mb-2">
                                    <div className="text-sm font-normal">
                                        Transient error generating the summary. Retrying...
                                    </div>
                                </LemonBanner>
                            )}
                            {summarizationProgress ? (
                                <SummarizationProgressView
                                    progress={summarizationProgress}
                                    sessionDurationMs={sessionPlayerData?.durationMs}
                                />
                            ) : (
                                <div className="flex items-center justify-between">
                                    <div>
                                        Researching the session... <Spinner />
                                    </div>
                                    <div className="flex items-center gap-1 ml-auto">
                                        <LoadingTimer />
                                    </div>
                                </div>
                            )}
                        </>
                    ) : sessionSummaryError ? (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Try again',
                                onClick: () => summarizeSession(),
                            }}
                        >
                            <div className="text-sm font-normal">
                                <strong>Summary failed.</strong> {sessionSummaryError}
                            </div>
                        </LemonBanner>
                    ) : hasSummary ? (
                        <SessionSummary />
                    ) : null}
                </div>
            )}
        </div>
    )
}
