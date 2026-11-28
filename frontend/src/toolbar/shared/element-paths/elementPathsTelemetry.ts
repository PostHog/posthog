import { toolbarPosthogJS } from '~/toolbar/shared/toolbarPosthogJS'

import type { ElementPathsView } from './elementPaths'

// pinned: analytics event names, renaming them breaks dashboards
const ELEMENT_PATHS_VIEWED = 'toolbar element journeys viewed'
const ELEMENT_PATHS_SAVE_CLICKED = 'toolbar element journeys save clicked'

/** `source: 'extension'` marks events that the extension panel sends for the page it shows. */
type TelemetrySource = { source?: 'extension' }

/** Sent once for each answer the section shows. A loading, hidden or idle section sends nothing. */
export function captureElementPathsViewed(view: ElementPathsView, { source }: TelemetrySource = {}): void {
    if (view.status === 'idle' || view.status === 'loading' || view.status === 'unavailable') {
        return
    }
    toolbarPosthogJS.capture(ELEMENT_PATHS_VIEWED, {
        result: view.status,
        path_count: 'result' in view ? view.result.paths.length : null,
        anchor_click_count: 'result' in view ? view.result.anchor_click_count : null,
        ...(source ? { source } : {}),
    })
}

export function captureElementPathsSaveClicked(
    view: ElementPathsView,
    pathIndex: number,
    { source }: TelemetrySource = {}
): void {
    const path = 'result' in view ? view.result.paths[pathIndex] : undefined
    if (!path) {
        return
    }
    toolbarPosthogJS.capture(ELEMENT_PATHS_SAVE_CLICKED, {
        path_index: pathIndex,
        step_count: path.nodes.length,
        has_approximate_steps: path.nodes.some((node) => !node.step_is_exact),
        share_of_anchor_sessions: path.share_of_anchor_sessions,
        ...(source ? { source } : {}),
    })
}
