import posthog from 'posthog-js'

// pinned: analytics event names and property names, shared with PostHog Desktop. Renaming breaks dashboards.
export const CANVAS_EVENTS = {
    dashboardAction: 'Dashboard action',
    promptSent: 'Canvas prompt sent',
    viewed: 'Canvas viewed',
    rendered: 'Canvas rendered',
    runtimeError: 'Canvas runtime error',
} as const

// pinned: `surface` values, shared with PostHog Desktop
export type CanvasSurface = 'web_new_canvas_page' | 'web_canvas_scene' | 'web_canvas_side_panel'

// pinned: `action_type` values of the Dashboard action event. "revert" is shared with PostHog
// Desktop. The rest name web actions Desktop does not track yet, so Desktop should reuse them.
export type CanvasDashboardActionType =
    | 'revert'
    | 'promote_draft'
    | 'panel_tab_change'
    | 'panel_toggle'
    | 'comment_create'
    | 'comment_reply'
    | 'comment_resolve'
    | 'build_retry'
    | 'build_cancel'
    | 'build_pin'
    | 'build_unpin'
    | 'fix_request'

/** Captures a canvas action from the scene or its side panel. Never pass prompt or comment text. */
export function captureCanvasAction(
    actionType: CanvasDashboardActionType,
    properties: {
        dashboard_id: string
        channel_id?: string
        surface?: CanvasSurface
        success?: boolean
        tab?: string
        open?: boolean
        origin?: 'build' | 'runtime'
        outcome?: string
    }
): void {
    posthog.capture(CANVAS_EVENTS.dashboardAction, {
        action_type: actionType,
        surface: 'web_canvas_scene',
        ...properties,
    })
}

/** Custom error names can carry viewer data, so only report fixed categories. */
export function canvasErrorType(message: string): string {
    const match = /^(Error|AggregateError|EvalError|RangeError|ReferenceError|SyntaxError|TypeError|URIError)\b/.exec(
        message.trim()
    )
    return match ? match[1] : 'unknown'
}
