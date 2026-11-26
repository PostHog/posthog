import type { NodeDetailTab, TraceOpeningMode } from './types'

// List ids are the `list` property of `llma trace drawer opened`, so renaming one breaks the event history.
export type TraceDrawerListId =
    | 'traces'
    | 'generations'
    | 'prompt-traces'
    | 'reviews'
    | 'review-queue'
    | 'evaluation-runs'
    | 'evaluation-preview'
    | 'dataset-items'
    | 'offline-experiment'
    | 'cluster-traces'
    | 'clusters'
    | 'eval-suggestions'
    | 'session-turns'
    | 'error-traces'
    | 'tool-traces'
    | 'person-traces'

export interface TraceDrawerListConfig {
    // Tested against the path without its project prefix. Other products use `trace` for their own ids, and on browser
    // back the outgoing list is still mounted on the next list's URL, so a list reads `trace` on its own path only.
    pathMatcher: RegExp
    backTo: string
    backLabel: string
    openingMode?: TraceOpeningMode
    detailTab?: NodeDetailTab
    rowClick: boolean
    showNavigation?: boolean
    /** For a list on a form: the full page opens in a new tab, so leaving does not drop unsaved edits. */
    fullPageInNewTab?: boolean
}

export const TRACE_DRAWER_LISTS: Record<TraceDrawerListId, TraceDrawerListConfig> = {
    traces: {
        pathMatcher: /^\/ai-observability\/traces$/,
        backTo: 'traces',
        backLabel: 'Back to traces',
        rowClick: true,
    },
    generations: {
        pathMatcher: /^\/ai-observability\/generations$/,
        backTo: 'generations',
        backLabel: 'Back to generations',
        rowClick: true,
    },
    'prompt-traces': {
        pathMatcher: /^\/prompt-management\/prompts\/[^/]+$/,
        backTo: 'prompt',
        backLabel: 'Back to prompt',
        rowClick: true,
    },
    reviews: {
        pathMatcher: /^\/ai-observability\/reviews$/,
        backTo: 'reviews',
        backLabel: 'Back to reviews',
        rowClick: true,
    },
    // Shares its path with reviews: the two are tabs of one scene, and only the open tab mounts its list. It also
    // shares the back target, because the trace page keeps queue context only for `back_to=reviews`.
    'review-queue': {
        pathMatcher: /^\/ai-observability\/reviews$/,
        backTo: 'reviews',
        backLabel: 'Back to reviews',
        rowClick: true,
    },
    'evaluation-runs': {
        pathMatcher: /^\/ai-evals\/evaluations\/(?!(?:templates|offline|scorers)$)[^/]+$/,
        backTo: 'evaluation',
        backLabel: 'Back to evaluation',
        detailTab: 'evals',
        rowClick: true,
    },
    // Shares its path with evaluation runs: the preview shows while setting the evaluation up, the runs list after.
    'evaluation-preview': {
        pathMatcher: /^\/ai-evals\/evaluations\/(?!(?:templates|offline|scorers)$)[^/]+$/,
        backTo: 'evaluation',
        backLabel: 'Back to evaluation',
        rowClick: true,
        fullPageInNewTab: true,
    },
    'dataset-items': {
        pathMatcher: /^\/ai-evals\/evaluations\/offline\/datasets\/[^/]+$/,
        backTo: 'dataset',
        backLabel: 'Back to dataset',
        rowClick: false,
    },
    'offline-experiment': {
        pathMatcher: /^\/ai-evals\/evaluations\/offline\/experiments\/[^/]+$/,
        backTo: 'offline-experiment',
        backLabel: 'Back to experiment',
        rowClick: false,
        showNavigation: false,
    },
    'cluster-traces': {
        pathMatcher: /^\/ai-observability\/clusters\/[^/]+\/[^/]+$/,
        backTo: 'cluster',
        backLabel: 'Back to cluster',
        openingMode: 'thread',
        rowClick: false,
    },
    clusters: {
        pathMatcher: /^\/ai-observability\/clusters(?:\/[^/]+)?$/,
        backTo: 'clusters',
        backLabel: 'Back to clusters',
        openingMode: 'thread',
        rowClick: false,
    },
    'eval-suggestions': {
        pathMatcher: /^\/ai-evals\/evaluations$/,
        backTo: 'evaluations',
        backLabel: 'Back to evaluations',
        rowClick: false,
    },
    // The split and the full page show the same conversation, so one list serves both.
    'session-turns': {
        pathMatcher: /^\/ai-observability\/sessions(\/[^/]+)?$/,
        backTo: 'session',
        backLabel: 'Back to session',
        rowClick: false,
        showNavigation: true,
    },
    // The three entity lists open traces from an entity drawer, so rows are not clickable here and stepping stays on.
    'error-traces': {
        pathMatcher: /^\/ai-observability\/errors$/,
        backTo: 'errors',
        backLabel: 'Back to errors',
        rowClick: false,
        showNavigation: true,
    },
    'tool-traces': {
        pathMatcher: /^\/ai-observability\/tools$/,
        backTo: 'tools',
        backLabel: 'Back to tools',
        rowClick: false,
        showNavigation: true,
    },
    'person-traces': {
        pathMatcher: /^\/ai-observability\/users$/,
        backTo: 'people',
        backLabel: 'Back to people',
        rowClick: false,
        showNavigation: true,
    },
}

const BACK_LABELS: ReadonlyMap<unknown, string> = new Map(
    Object.values(TRACE_DRAWER_LISTS).map(({ backTo, backLabel }) => [backTo, backLabel])
)

export function traceDrawerBackLabel(backTo: unknown): string {
    return BACK_LABELS.get(backTo) ?? 'Back'
}
