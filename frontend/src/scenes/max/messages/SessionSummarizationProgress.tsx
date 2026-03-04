import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress/LemonProgress'

const VIDEO_ANALYSIS_PLAYBACK_SPEED = 8

interface SessionInfo {
    first_url: string
    active_duration_s: number
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
    watching_sessions: 'Analyzing sessions',
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

function truncateUrl(url: string, maxLen = 40): string {
    if (url.length <= maxLen) {
        return url
    }
    return url.slice(0, maxLen - 1) + '…'
}

function deriveState(updates: object[]): DerivedState {
    const sessions = new Map<string, SessionInfo>()
    let phase = 'fetching_data'
    let completedCount = 0
    let totalCount = 0
    let patternsFound: string[] = []

    for (const update of updates) {
        const u = update as Record<string, unknown>
        if (u.type === 'sessions_discovered') {
            const sessionsList = u.sessions as Array<{ id: string; first_url: string; active_duration_s: number }>
            for (const s of sessionsList) {
                sessions.set(s.id, { first_url: s.first_url, active_duration_s: s.active_duration_s, status: 'queued' })
            }
            totalCount = sessionsList.length
        } else if (u.type === 'progress') {
            const statusChanges = u.status_changes as Array<{ id: string; status: string }>
            if (statusChanges) {
                for (const change of statusChanges) {
                    const existing = sessions.get(change.id)
                    if (existing) {
                        existing.status = change.status
                    } else {
                        sessions.set(change.id, { first_url: '', active_duration_s: 0, status: change.status })
                    }
                }
            }
            if (typeof u.phase === 'string') {
                phase = u.phase
            }
            if (typeof u.completed_count === 'number') {
                completedCount = u.completed_count
            }
            if (typeof u.total_count === 'number') {
                totalCount = u.total_count
            }
            if (Array.isArray(u.patterns_found) && u.patterns_found.length > 0) {
                patternsFound = u.patterns_found as string[]
            }
        }
    }

    // Adjust for skipped sessions
    let skippedCount = 0
    for (const s of sessions.values()) {
        if (s.status === 'skipped') {
            skippedCount++
        }
    }
    totalCount = Math.max(totalCount - skippedCount, 0)

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

export function SessionSummarizationProgress({ updates }: { updates: object[] }): JSX.Element {
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
                    {PHASE_LABELS[phase] || phase}
                    {phase === 'watching_sessions' && totalCount > 0 && (
                        <span className="text-muted ml-1">
                            ({completedCount}/{totalCount})
                        </span>
                    )}
                </span>
                {etaText && <span className="text-xs text-muted">{etaText}</span>}
            </div>

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
                                    <Tooltip title={session.first_url || id}>
                                        <Link to={`/replay/${id}`} target="_blank" className="truncate max-w-60">
                                            {session.first_url ? truncateUrl(session.first_url) : id.slice(0, 8)}
                                        </Link>
                                    </Tooltip>
                                    {session.active_duration_s > 0 && (
                                        <span className="text-muted ml-auto shrink-0">
                                            {formatDuration(session.active_duration_s)}
                                        </span>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
