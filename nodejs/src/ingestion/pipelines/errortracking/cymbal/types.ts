/**
 * Exception frame in a stack trace.
 */
export interface ExceptionFrame {
    filename?: string
    abs_path?: string
    lineno?: number
    colno?: number
    function?: string
    context_line?: string
    pre_context?: string[]
    post_context?: string[]
    in_app?: boolean
    vars?: Record<string, any>
    // Source map resolved fields
    resolved_name?: string
    resolved?: boolean
    resolve_failure?: string
}

/**
 * Single exception entry in the exception list.
 */
export interface ExceptionEntry {
    type: string
    value: string
    module?: string
    thread_id?: number
    mechanism?: {
        type: string
        handled: boolean
        synthetic?: boolean
        description?: string
        help_link?: string
        data?: Record<string, any>
    }
    stacktrace?: {
        type?: 'raw' | 'resolved'
        frames: ExceptionFrame[]
    }
}

/**
 * Cymbal API request format.
 *
 * Matches Cymbal's AnyEvent struct - properties contains $exception_list and all other event properties.
 */
export interface CymbalRequest {
    uuid: string
    event: string
    team_id: number
    timestamp: string
    properties: Record<string, any>
}

/**
 * Cymbal API response format.
 *
 * Cymbal returns the same AnyEvent structure with modified properties.
 * Returns null for suppressed events (e.g., issue marked as suppressed).
 */
export interface CymbalResponse {
    uuid: string
    event: string
    team_id: number
    timestamp: string
    properties: Record<string, any>
}
