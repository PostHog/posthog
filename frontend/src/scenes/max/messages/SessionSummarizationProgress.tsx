import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress/LemonProgress'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

const VIDEO_ANALYSIS_PLAYBACK_SPEED = 8 // Speed must be same as in the backend

interface SessionDiscoveredUpdate {
    type: 'sessions_discovered'
    sessions: {
        id: string
        first_url: string
        active_duration_s: number
        distinct_id: string
        start_time: string | null
        snapshot_source: 'web' | 'mobile'
    }[]
}

interface SessionProgressUpdate {
    type: 'progress'
    status_changes: { id: string; status: string }[]
    phase: string
    completed_count: number
    total_count: number
    patterns_found: string[]
}

export type SessionSummarizationUpdate = SessionDiscoveredUpdate | SessionProgressUpdate

interface SessionInfo {
    first_url: string
    active_duration_s: number
    distinct_id: string
    start_time: string | null
    snapshot_source: 'web' | 'mobile'
    status: string
}

interface DerivedState {
    sessions: Map<string, SessionInfo>
    phase: string
    completedCount: number
    totalCount: number
    patternsFound: string[]
}

const PHASE_LABELS: Record<string, string> = {
    fetching_data: 'Fetching session data',
    watching_sessions: 'Watching sessions',
    extracting_patterns: 'Searching for patterns',
    assigning_patterns: 'Building report',
}

function formatDuration(seconds: number): string {
    if (seconds < 60) {
        return `${seconds}s`
    }
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
}

function formatEta(seconds: number): string {
    if (seconds <= 0) {
        return 'almost done'
    }
    // Round to nearest 5s to avoid jitter
    const rounded = Math.round(seconds / 5) * 5
    if (rounded < 60) {
        return `~${Math.max(rounded, 5)} seconds remaining`
    }
    const mins = Math.ceil(rounded / 60)
    return `~${mins} ${mins === 1 ? 'minute' : 'minutes'} remaining`
}

function deriveState(updates: SessionSummarizationUpdate[]): DerivedState {
    const sessions = new Map<string, SessionInfo>()
    let phase = 'fetching_data'
    let completedCount = 0
    let totalCount = 0
    let patternsFound: string[] = []

    for (const update of updates) {
        if (update.type === 'sessions_discovered') {
            for (const s of update.sessions) {
                sessions.set(s.id, {
                    first_url: s.first_url,
                    active_duration_s: s.active_duration_s,
                    distinct_id: s.distinct_id,
                    start_time: s.start_time,
                    snapshot_source: s.snapshot_source,
                    status: 'queued',
                })
            }
            totalCount = update.sessions.length
        } else if (update.type === 'progress') {
            for (const change of update.status_changes) {
                const existing = sessions.get(change.id)
                if (existing) {
                    existing.status = change.status
                } else {
                    sessions.set(change.id, {
                        first_url: '',
                        active_duration_s: 0,
                        distinct_id: '',
                        start_time: null,
                        snapshot_source: 'web',
                        status: change.status,
                    })
                }
            }
            phase = update.phase
            completedCount = update.completed_count
            totalCount = update.total_count
            if (update.patterns_found.length > 0) {
                patternsFound = update.patterns_found
            }
        }
    }

    return { sessions, phase, completedCount, totalCount, patternsFound }
}

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

    return (
        <div className="flex flex-col gap-2 py-2 px-1 w-full">
            {totalCount > 0 && <LemonProgress percent={progressPercent} bgColor="var(--color-bg-surface-tertiary)" />}
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
                <ScrollableShadows
                    direction="vertical"
                    innerClassName="flex flex-col gap-0.5"
                    className="max-h-60 rounded"
                >
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
                                <TZLabel className="text-muted shrink-0" time={session.start_time} placement="right" />
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
                </ScrollableShadows>
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
