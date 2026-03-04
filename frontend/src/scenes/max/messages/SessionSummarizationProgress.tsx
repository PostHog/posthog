import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress/LemonProgress'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import {
    deriveState,
    formatDuration,
    formatEta,
    PHASE_LABELS,
    type SessionSummarizationUpdate,
} from './sessionSummarizationProgressUtils'

export type { SessionSummarizationUpdate } from './sessionSummarizationProgressUtils'

const VIDEO_ANALYSIS_PLAYBACK_SPEED = 8 // Speed must be same as in the backend

function StatusIcon({ status }: { status: string }): JSX.Element {
    switch (status) {
        case 'summarizing':
            return <Spinner textColored className="size-3.5" />
        case 'summarized':
            return <IconCheck className="text-success size-3.5" />
        case 'failed':
            return <IconX className="text-danger size-3.5" />
        case 'skipped':
            return <span className="size-3.5 inline-flex items-center justify-center text-muted">–</span>
        default:
            // queued
            return <span className="size-2 rounded-full bg-muted-3000 inline-block" />
    }
}

export function SessionSummarizationProgress({ updates }: { updates: SessionSummarizationUpdate[] }): JSX.Element {
    const state = useMemo(() => deriveState(updates), [updates])
    const { sessions, phase, completedCount, totalCount, patternsFound } = state
    const [isExpanded, setIsExpanded] = useState(false)

    // ETA: max active duration among remaining sessions (concurrent processing, so longest one determines wait)
    const summarizingStartedAt = useRef<number | null>(null)
    const [, setTick] = useState(0)

    useEffect(() => {
        if (phase === 'watching_sessions' && summarizingStartedAt.current === null) {
            summarizingStartedAt.current = Date.now()
        }
    }, [phase])

    // Tick every second during watching_sessions phase for ETA countdown
    useEffect(() => {
        if (phase !== 'watching_sessions' || completedCount >= totalCount || totalCount === 0) {
            return
        }
        const interval = setInterval(() => setTick((t) => t + 1), 1000)
        return () => clearInterval(interval)
    }, [phase, completedCount, totalCount])

    const progressPercent = totalCount > 0 ? (completedCount / totalCount) * 100 : 0
    const isComplete = completedCount >= totalCount && totalCount > 0

    // ETA based on remaining sessions' active durations at playback speed
    let etaText: string | null = null
    if (phase === 'watching_sessions' && !isComplete && summarizingStartedAt.current) {
        let maxRemainingDuration = 0
        for (const [, session] of sessions) {
            if (session.status === 'queued' || session.status === 'summarizing') {
                maxRemainingDuration = Math.max(maxRemainingDuration, session.active_duration_s)
            }
        }
        // Analysis watches at VIDEO_ANALYSIS_PLAYBACK_SPEED, plus ~90s overhead for video export/processing
        const analysisTime = maxRemainingDuration / VIDEO_ANALYSIS_PLAYBACK_SPEED + 90
        // Subtract elapsed time since we started (sessions run concurrently)
        const elapsed = (Date.now() - summarizingStartedAt.current) / 1000
        const remaining = analysisTime - elapsed
        if (remaining > 0) {
            etaText = formatEta(remaining)
        }
    }

    const sessionEntries = Array.from(sessions.entries()).filter(([, s]) => s.status !== 'skipped')
    const showCollapse = sessionEntries.length > 20

    return (
        <div className="flex flex-col gap-2 py-2 px-1 w-full">
            {totalCount > 0 && <LemonProgress percent={progressPercent} />}
            <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-secondary">
                    {PHASE_LABELS[phase] || phase}…
                    {phase === 'watching_sessions' && totalCount > 0 && (
                        <span className="text-muted ml-1">
                            ({completedCount}/{totalCount})
                        </span>
                    )}
                </span>
                {etaText && <span className="text-xs text-muted">{etaText}</span>}
            </div>

            {sessionEntries.length > 0 && (
                <div>
                    {showCollapse && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => setIsExpanded(!isExpanded)}
                            className="mb-1"
                        >
                            {isExpanded ? 'Hide sessions' : `Show all ${sessionEntries.length} sessions`}
                        </LemonButton>
                    )}
                    {(!showCollapse || isExpanded) && (
                        <div className="flex flex-col gap-0.5 max-h-60 overflow-y-auto">
                            {sessionEntries.map(([id, session]) => (
                                <div
                                    key={id}
                                    className="flex items-center gap-1.5 text-xs py-0.5 px-1 rounded hover:bg-fill-button-tertiary-hover"
                                >
                                    <StatusIcon status={session.status} />
                                    <PropertyIcon
                                        property="$device_type"
                                        value={session.snapshot_source === 'mobile' ? 'Mobile' : 'Desktop'}
                                        className="text-muted shrink-0"
                                    />
                                    <PersonDisplay
                                        person={session.distinct_id ? { distinct_id: session.distinct_id } : undefined}
                                        href={`/replay/${id}`}
                                        maxLength={13}
                                        withIcon="xs"
                                        noPopover
                                        noEllipsis
                                    />
                                    {session.start_time && (
                                        <TZLabel
                                            className="text-muted shrink-0"
                                            time={session.start_time}
                                            placement="right"
                                        />
                                    )}
                                    {session.active_duration_s > 0 && (
                                        <Tooltip title="Duration of active interaction in this session">
                                            <span className="text-muted ml-auto shrink-0 select-none">
                                                {formatDuration(session.active_duration_s)}
                                            </span>
                                        </Tooltip>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {patternsFound.length > 0 && (phase === 'extracting_patterns' || phase === 'assigning_patterns') && (
                <div className="text-xs text-secondary">
                    <span className="font-medium">Patterns found:</span>
                    <ul className="list-disc list-inside mt-0.5">
                        {patternsFound.map((p) => (
                            <li key={p}>{p}</li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}
