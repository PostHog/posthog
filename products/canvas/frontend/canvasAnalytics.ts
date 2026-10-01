// pinned: analytics event names and property names, shared with PostHog Desktop. Renaming breaks dashboards.
export const CANVAS_EVENTS = {
    dashboardAction: 'Dashboard action',
    promptSent: 'Canvas prompt sent',
    viewed: 'Canvas viewed',
    rendered: 'Canvas rendered',
    runtimeError: 'Canvas runtime error',
} as const

// pinned: `surface` values, shared with PostHog Desktop
export type CanvasSurface = 'web_new_canvas_page' | 'web_canvas_scene'

/** The error's class name, never its message: canvas errors can carry source, data, or secrets. */
export function canvasErrorType(message: string): string {
    const match = /^([A-Z][A-Za-z]*Error)\b/.exec(message.trim())
    return match ? match[1] : 'unknown'
}
