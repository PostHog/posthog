import posthog from 'posthog-js'

import type { TraceDrawerListId } from './traceDrawerLists'
import type { SummaryOpenedFrom } from './traceSummaryLogic'
import type { FeedbackEntry, MessagesOpening, NodeLoadTrigger, SummaryItemKind, SummaryModeState } from './types'

/**
 * Usage tracking for the trace view, on the trace page and in the trace drawer.
 *
 * These events record only what autocapture cannot see: actions that are not clicks (keys, links, steps the view
 * selects itself) and outcomes (loads, searches, summaries, copies). Clicks have no event here. Autocapture records
 * each click as `$autocapture`, and the clicked element or its nearest ancestor carries a `trace-view-*` or
 * `trace-drawer-*` `data-attr` that names it. To count clicks, match `elements_chain` on those `data-attr` values and
 * group by the first one in the chain. Autocapture does not record clicks into text inputs, so count searches with
 * `searched` and not with clicks on `trace-view-search-input`. Some tagged elements, such as the review and git branch
 * chips, only display a value and cannot be clicked.
 *
 * To follow a person through the view, order these events, `$autocapture` and `$pageview` by `$session_id` and
 * timestamp. `$current_url` identifies the open trace: the trace page path, or the list URL with the drawer's `trace`
 * param.
 *
 * The server sends the events for actions that save something: `llma trace review created`, `updated` and `deleted`
 * (`backend/api/trace_reviews.py`), `llma dataset item created` (`backend/api/datasets.py`) and
 * `llma trace export downloaded` (`backend/presentation/views.py`). They take `$session_id` and `$current_url` from
 * the request headers, so they order with the events here.
 */

// pinned: event names and property keys. Dashboards, insights and usage analysis read them, so a rename breaks them.
const EVENTS = {
    viewLoaded: 'llma trace view loaded',
    nodeLoaded: 'llma trace node loaded',
    drawerOpened: 'llma trace drawer opened',
    drawerStepped: 'llma trace drawer stepped',
    drawerClosed: 'llma trace drawer closed',
    messagesOpeningSwitched: 'llma trace messages opening switched',
    searched: 'llma trace view searched',
    summaryViewed: 'llma trace view summary viewed',
    summaryRequested: 'llma trace view summary requested',
    summaryShown: 'llma trace view summary shown',
    summaryStepClicked: 'llma trace view summary step clicked',
    feedbackViewed: 'llma trace view feedback viewed',
    exportCopied: 'llma trace export copied',
    exportCopyFailed: 'llma trace export copy failed',
} as const

export type SummaryShownSource = 'just_generated' | 'stored'
export type CopyFailureReason = 'too_large' | 'export_failed' | 'error'

export interface TraceFeedbackCounts {
    scores: number | null
    responses: number | null
    unanswered: number | null
}

export const traceViewTracking = {
    /**
     * Sent each time the trace resource answers: on the trace page, and for each trace the drawer opens or steps to.
     * `trace_load_ms` is the wait for that read. `node_count` counts every step, the root included.
     */
    viewLoaded: (traceLoadMs: number, nodeCount: number): void => {
        posthog.capture(EVENTS.viewLoaded, { trace_load_ms: traceLoadMs, node_count: nodeCount })
    },
    /**
     * Sent when the content of a step loads. A failed read sends no event, because it reports through error tracking.
     *
     * `trigger` says what started the read:
     * - `selection`: a click on the step.
     * - `navigation`: a step the view selected without a click, such as the default step, an `event` link or browser
     *   history.
     * - `prefetch`: a hover over the step's tree row. This is not a user action, so leave it out of usage counts.
     * - `thread`: a read that the Thread mode starts for its generations.
     *
     * `load_ms` runs from the first request for the step, retries included. `waited_ms` runs from a click on the step
     * to its content, and is null when nobody clicked before the content was ready. A click during a prefetch does not
     * start a second read, so a `prefetch` event can carry `waited_ms`.
     */
    nodeLoaded: (trigger: NodeLoadTrigger, loadMs: number, waitedMs: number | null): void => {
        posthog.capture(EVENTS.nodeLoaded, { load_ms: loadMs, trigger, waited_ms: waitedMs })
    },
    /**
     * Sent when the drawer opens over a list. Stepping to another trace in the drawer does not send it again.
     * `list` names the list, and is one of the `TraceDrawerListId` values.
     */
    drawerOpened: (list: TraceDrawerListId): void => {
        posthog.capture(EVENTS.drawerOpened, { list })
    },
    /**
     * Sent when the drawer moves to the next or previous trace, by its toolbar buttons or by the N and P keys. To get
     * the steps by key, subtract the `trace-drawer-next` and `trace-drawer-previous` clicks.
     */
    drawerStepped: (direction: 'next' | 'previous'): void => {
        posthog.capture(EVENTS.drawerStepped, { direction })
    },
    /**
     * Sent when the drawer closes by any route: its close button, Escape, browser history or leaving the list. Count
     * closes with this event, because the `trace-drawer-close` clicks miss the other routes. `steps` counts the
     * `drawerStepped` events since the drawer opened.
     */
    drawerClosed: (steps: number): void => {
        posthog.capture(EVENTS.drawerClosed, { steps })
    },
    /** Sent when the person changes how the Messages tab opens. The choice persists per browser. */
    messagesOpeningSwitched: (to: MessagesOpening): void => {
        posthog.capture(EVENTS.messagesOpeningSwitched, { to })
    },
    /**
     * Sent when a search within the trace answers. The box sends a request after typing pauses, so one search can
     * send more than one event. A trace that loads with a query in the box searches again. `query_length` is the
     * length of the trimmed query, `total` counts all matches and `matching_steps` counts the steps that match.
     */
    searched: (queryLength: number, total: number, matchingSteps: number, loadMs: number): void => {
        posthog.capture(EVENTS.searched, {
            query_length: queryLength,
            total,
            matching_steps: matchingSteps,
            load_ms: loadMs,
        })
    },
    /**
     * Sent each time the Summary mode opens, when its first read answers. `has_summary` is true when a stored summary exists.
     * `can_generate` is false when the organization has not approved AI data processing or the person cannot edit.
     * `opened_from` is `tab` for the mode tab, or `link` for a link that opens the trace in the Summary mode.
     */
    summaryViewed: (
        hasSummary: boolean,
        status: SummaryModeState['status'],
        canGenerate: boolean,
        openedFrom: SummaryOpenedFrom
    ): void => {
        posthog.capture(EVENTS.summaryViewed, {
            has_summary: hasSummary,
            status,
            can_generate: canGenerate,
            opened_from: openedFrom,
        })
    },
    /** Sent when the person asks for a summary, or for a new one when `regenerate` is true. */
    summaryRequested: (regenerate: boolean): void => {
        posthog.capture(EVENTS.summaryRequested, { regenerate })
    },
    /**
     * Sent once per summary that appears in the Summary mode. `source` is `just_generated` when the person waited for
     * it in this visit, and `stored` when it existed before.
     */
    summaryShown: (source: SummaryShownSource): void => {
        posthog.capture(EVENTS.summaryShown, { source })
    },
    /** Sent when a bullet or a note of the summary opens its step. */
    summaryStepClicked: (kind: SummaryItemKind): void => {
        posthog.capture(EVENTS.summaryStepClicked, { kind })
    },
    /**
     * Sent when the Feedback mode opens. `entry` is `chip` for the header's feedback chip, `step` for the feedback
     * chips of a step, and `tab` for the mode tab. The counts are null while the trace's feedback is still loading.
     */
    feedbackViewed: (entry: FeedbackEntry | 'tab', counts: TraceFeedbackCounts): void => {
        posthog.capture(EVENTS.feedbackViewed, { entry, ...counts })
    },
    /**
     * Sent when the trace reaches the clipboard. `fallback` is true when the browser refused the direct write and the
     * person used the Copy button of the toast instead.
     */
    exportCopied: (sizeBytes: number, fallback: boolean): void => {
        posthog.capture(EVENTS.exportCopied, { size_bytes: sizeBytes, fallback })
    },
    /** Sent when a copy fails. `too_large` means the trace is over the copy limit and the toast offers a download. */
    exportCopyFailed: (reason: CopyFailureReason): void => {
        posthog.capture(EVENTS.exportCopyFailed, { reason })
    },
}
