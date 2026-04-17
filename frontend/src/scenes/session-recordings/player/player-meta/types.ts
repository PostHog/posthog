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

/** Structured heartbeat payload emitted by the Node.js rasterizer activity. */
export interface RasterizerFrameProgress {
    phase: 'setup' | 'capture' | 'upload'
    frame: number
    estimatedTotalFrames: number
}

/** Coarse phase of the rasterizer child workflow plus fine-grained frame counts. */
export interface RasterizerProgress {
    phase: string
    frame_progress: RasterizerFrameProgress | null
}

/** Progress snapshot emitted by the `session-summary-progress` SSE event (video flow only). */
export interface SummarizationProgress {
    phase: string
    step: number
    total_steps: number
    rasterizer_workflow_id: string | null
    segments_total: number
    segments_completed: number
    rasterizer: RasterizerProgress | null
}
