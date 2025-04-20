export interface SessionKeyAction {
    description?: string | null
    error?: boolean | null
    event_id?: string | null
    timestamp?: string | null
    milliseconds_since_start?: number | null
    window_id?: string | null
    current_url?: string | null
    event?: string | null
    event_type?: string | null
    event_index?: number | null
}

export interface SessionSegmentKeyActions {
    segment?: string | null
    events?: SessionKeyAction[] | null
}

export interface SessionSegment {
    name?: string | null
    summary?: string | null
    success?: boolean | null
    start_event_id?: string | null
    end_event_id?: string | null
}

export interface SessionOutcome {
    description?: string | null
    success?: boolean | null
}

export interface SessionSummaryContent {
    segments?: SessionSegment[] | null
    key_actions?: SessionSegmentKeyActions[] | null
    session_outcome?: SessionOutcome | null
}
