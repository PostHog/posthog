export interface SessionKeyAction {
    description?: string | null
    abandonment?: boolean | null
    confusion?: boolean | null
    exception?: 'blocking' | 'non-blocking' | null
    event_id?: string | null
    timestamp?: string | null
    milliseconds_since_start?: number | null
    window_id?: string | null
    current_url?: string | null
    event?: string | null
    event_type?: string | null
    event_index?: number | null
    event_uuid?: string | null
    session_id?: string | null
}

export interface SessionSegmentKeyActions {
    segment_index?: number | null
    events?: SessionKeyAction[] | null
}

export interface SegmentMeta {
    duration?: number | null
    duration_percentage?: number | null
    events_count?: number | null
    events_percentage?: number | null
    key_action_count?: number | null
    failure_count?: number | null
    abandonment_count?: number | null
    confusion_count?: number | null
    exception_count?: number | null
}

export interface SessionSegment {
    index?: number | null
    name?: string | null
    start_event_id?: string | null
    end_event_id?: string | null
    meta?: SegmentMeta | null
}

export interface SessionSegmentOutcome {
    segment_index?: number | null
    summary?: string | null
    success?: boolean | null
}

export interface SessionOutcome {
    description?: string | null
    success?: boolean | null
}

export interface SessionSummaryContent {
    segments?: SessionSegment[] | null
    key_actions?: SessionSegmentKeyActions[] | null
    segment_outcomes?: SessionSegmentOutcome[] | null
    session_outcome?: SessionOutcome | null
}
