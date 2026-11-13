import posthog from 'posthog-js'

// pinned: analytics event names and property names, shared with PostHog Desktop. Renaming breaks dashboards.
export const CANVAS_EVENTS = {
    dashboardAction: 'Dashboard action',
    viewed: 'Canvas viewed',
    rendered: 'Canvas rendered',
    runtimeError: 'Canvas runtime error',
} as const

// pinned: `surface` values, shared with PostHog Desktop
export type CanvasSurface = 'web_canvas_scene' | 'web_canvas_side_panel' | 'web_canvases_list' | 'web_dashboard_widget'

// pinned: `action_type` values of the Dashboard action event. They name web actions PostHog Desktop does not track yet, so Desktop should reuse them.
export type CanvasDashboardActionType =
    | 'panel_tab_change'
    | 'panel_toggle'
    | 'fullscreen_toggle'
    | 'comment_create'
    | 'comment_open'
    | 'comment_reply'
    | 'comment_resolve'
    | 'make_public_opened'
    | 'visibility_change'

/** Captures a canvas action from the scene or its side panel. Never pass prompt, comment, or source text. */
export function captureCanvasAction(
    actionType: CanvasDashboardActionType,
    properties: {
        dashboard_id: string
        channel_id?: string
        surface?: CanvasSurface
        success?: boolean
        tab?: string
        source?: 'highlight' | 'menu'
        open?: boolean
        /** visibility_change: who can see the canvas after the change. */
        visibility?: 'private' | 'public'
        /** visibility_change: whether the change undid the one before. */
        undo?: boolean
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
