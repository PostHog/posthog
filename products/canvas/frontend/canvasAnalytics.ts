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

// pinned: `action_type` values of the Dashboard action event. "revert" and "edit_toggle" are shared
// with PostHog Desktop. The rest name web actions Desktop does not track yet, so Desktop should reuse them.
export type CanvasDashboardActionType =
    | 'revert'
    | 'edit_toggle'
    | 'block_insert'
    | 'block_move'
    | 'block_edit'
    | 'block_remove'
    | 'block_duplicate'
    | 'text_edit'
    | 'edit_undo'
    | 'edit_redo'
    | 'edit_save'
    | 'edit_conflict'
    | 'edit_conflict_resolve'
    | 'promote_draft'
    | 'panel_tab_change'
    | 'panel_toggle'
    | 'fullscreen_toggle'
    | 'comment_create'
    | 'comment_open'
    | 'comment_reply'
    | 'comment_resolve'
    | 'build_retry'
    | 'build_cancel'
    | 'build_pin'
    | 'build_unpin'
    | 'fix_request'

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
        origin?: 'build' | 'runtime'
        outcome?: string
        /** edit_toggle: the state being entered. */
        editing?: boolean
        /** A library block type, "custom" for a component the agent wrote, or "element" for plain markup. */
        block_type?: string
        /** block_insert: whether the block was clicked in or dragged in. */
        method?: 'click' | 'drag'
        /** edit_conflict_resolve: whether the author kept their edits over the newer version. */
        keep_local?: boolean
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
