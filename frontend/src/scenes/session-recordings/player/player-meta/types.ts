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

export interface SessionObjectiveKeyActions {
    objective?: string | null
    events?: SessionKeyAction[] | null
}

export interface SessionObjective {
    name?: string | null
    summary?: string | null
    success?: boolean | null
}

export interface SessionOutcome {
    description?: string | null
    success?: boolean | null
}

export interface SessionSummaryContent {
    objectives?: SessionObjective[] | null
    key_actions?: SessionObjectiveKeyActions[] | null
    session_outcome?: SessionOutcome | null
}
