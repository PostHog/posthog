export interface SessionKeyEvent {
    description: string
    error: boolean
    tags: {
        where: string[]
        what: string[]
    }
    timestamp: string
    milliseconds_since_start: number
    window_id: string
    current_url: string
    event: string
    event_type: string | null
    importance: number
}

export interface SessionSummaryContent {
    summary: string
    key_events: SessionKeyEvent[]
}

export interface SessionSummaryResponse {
    content: SessionSummaryContent
}
