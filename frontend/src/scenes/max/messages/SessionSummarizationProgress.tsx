import { useMemo, useRef, useState } from 'react'

import { IconCheck, IconChevronRight, IconX } from '@posthog/icons'
import { Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'

interface SessionDiscoveredUpdate {
    type: 'sessions_discovered'
    sessions: { id: string; first_url: string; duration_s: number }[]
}

interface ProgressUpdate {
    type: 'progress'
    status_changes: { id: string; status: string }[]
    phase: string
    completed_count: number
    total_count: number
}

type StructuredUpdate = SessionDiscoveredUpdate | ProgressUpdate

interface DerivedSessionState {
    first_url: string
    duration_s: number
    status: string
}

interface DerivedState {
    sessions: Map<string, DerivedSessionState>
    phase: string
    completedCount: number
    totalCount: number
}

const PHASE_LABELS: Record<string, string> = {
    fetching_data: 'Fetching session data',
    watching_sessions: 'Watching sessions',
    extracting_patterns: 'Extracting behavior patterns',
    assigning_patterns: 'Generating report',
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

function formatEta(seconds: number): string {
    if (seconds < 60) {
        return `~${Math.max(1, Math.round(seconds))} seconds remaining`
    }
    const minutes = Math.ceil(seconds / 60)
    return `~${minutes} ${minutes === 1 ? 'minute' : 'minutes'} remaining`
}

function StatusIcon({ status }: { status: string }): JSX.Element {
    switch (status) {
        case 'summarizing':
            return <Spinner size="small" className="size-3.5" />
        case 'summarized':
            return <IconCheck className="text-success size-3.5" />
        case 'failed':
            return <IconX className="text-danger size-3.5" />
        case 'skipped':
            return <span className="size-3.5 flex items-center justify-center text-muted italic text-[10px]">skip</span>
        case 'queued':
        default:
            return <span className="size-3.5 flex items-center justify-center text-muted">&middot;</span>
    }
}

export function SessionSummarizationProgress({ updates }: { updates: object[] }): JSX.Element {
    const firstCompletionTimeRef = useRef<number | null>(null)
    const [isExpanded, setIsExpanded] = useState(false)

    const derivedState = useMemo<DerivedState>(() => {
        const sessions = new Map<string, DerivedSessionState>()
        let phase = 'fetching_data'
        let completedCount = 0
        let totalCount = 0

        for (const update of updates as StructuredUpdate[]) {
            if (update.type === 'sessions_discovered') {
                for (const session of update.sessions) {
                    sessions.set(session.id, {
                        first_url: session.first_url,
                        duration_s: session.duration_s,
                        status: 'queued',
                    })
                }
                totalCount = update.sessions.length
            } else if (update.type === 'progress') {
                phase = update.phase
                completedCount = update.completed_count
                totalCount = update.total_count
                for (const change of update.status_changes) {
                    const existing = sessions.get(change.id)
                    if (existing) {
                        existing.status = change.status
                    } else {
                        sessions.set(change.id, { first_url: '', duration_s: 0, status: change.status })
                    }
                }
            }
        }

        return { sessions, phase, completedCount, totalCount }
    }, [updates])

    // Track first completion time for ETA
    if (derivedState.completedCount > 0 && firstCompletionTimeRef.current === null) {
        firstCompletionTimeRef.current = Date.now()
    }

    const etaText = useMemo(() => {
        if (
            !firstCompletionTimeRef.current ||
            derivedState.completedCount === 0 ||
            derivedState.completedCount >= derivedState.totalCount
        ) {
            return null
        }
        const elapsed = (Date.now() - firstCompletionTimeRef.current) / 1000
        const rate = derivedState.completedCount / elapsed
        if (rate <= 0) {
            return null
        }
        const remaining = (derivedState.totalCount - derivedState.completedCount) / rate
        return formatEta(remaining)
    }, [derivedState.completedCount, derivedState.totalCount])

    const { sessions, phase, completedCount, totalCount } = derivedState
    const percent = totalCount > 0 ? (completedCount / totalCount) * 100 : 0
    const sessionEntries = Array.from(sessions.entries())
    const showCollapsible = sessionEntries.length > 20

    return (
        <div className="flex flex-col gap-1.5 text-xs mt-1 border-l-2 border-border-secondary pl-3.5 ml-[calc(0.775rem)]">
            <LemonProgress percent={percent} size="medium" className="w-full" />
            <div className="flex items-center gap-2 text-muted">
                <span>{PHASE_LABELS[phase] || phase}</span>
                {totalCount > 0 && (
                    <span>
                        ({completedCount}/{totalCount})
                    </span>
                )}
                {etaText && <span className="text-muted">{etaText}</span>}
            </div>
            {sessionEntries.length > 0 && (
                <>
                    {showCollapsible && (
                        <button
                            className="flex items-center gap-1 text-muted cursor-pointer hover:text-default transition-colors text-left"
                            onClick={() => setIsExpanded(!isExpanded)}
                        >
                            <span className={cn('transform transition-transform', isExpanded && 'rotate-90')}>
                                <IconChevronRight className="size-3" />
                            </span>
                            <span>{isExpanded ? 'Hide' : 'Show'} session details</span>
                        </button>
                    )}
                    {(!showCollapsible || isExpanded) && (
                        <div className="flex flex-col gap-0.5 max-h-80 overflow-y-auto">
                            {sessionEntries.map(([id, session]) => (
                                <div key={id} className="flex items-center gap-1.5 min-w-0">
                                    <StatusIcon status={session.status} />
                                    <Tooltip title={session.first_url || id}>
                                        <Link
                                            href={`/replay/${id}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="truncate text-link max-w-60 hover:underline"
                                        >
                                            {session.first_url || id.slice(0, 8)}
                                        </Link>
                                    </Tooltip>
                                    {session.duration_s > 0 && (
                                        <span className="text-muted flex-shrink-0">
                                            {formatDuration(session.duration_s)}
                                        </span>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
