export interface SessionDiscoveredUpdate {
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

export interface SessionProgressUpdate {
    type: 'progress'
    status_changes: { id: string; status: string }[]
    phase: string
    completed_count: number
    total_count: number
    patterns_found: string[]
}

export type SessionSummarizationUpdate = SessionDiscoveredUpdate | SessionProgressUpdate

export interface SessionInfo {
    first_url: string
    active_duration_s: number
    distinct_id: string
    start_time: string | null
    snapshot_source: 'web' | 'mobile'
    status: string
}

export interface DerivedState {
    sessions: Map<string, SessionInfo>
    phase: string
    completedCount: number
    totalCount: number
    patternsFound: string[]
}

export const PHASE_LABELS: Record<string, string> = {
    fetching_data: 'Fetching session data',
    watching_sessions: 'Watching sessions',
    extracting_patterns: 'Searching for patterns',
    assigning_patterns: 'Building report',
}

export function formatDuration(seconds: number): string {
    if (seconds < 60) {
        return `${seconds}s`
    }
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
}

export function formatEta(seconds: number): string {
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

export function deriveState(updates: SessionSummarizationUpdate[]): DerivedState {
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
