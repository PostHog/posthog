import type { QueryTab } from './multitabEditorLogic'

export interface UrlParams {
    searchParams: {
        open_view?: string
        open_insight?: string
        open_draft?: string
        open_query?: string
        output_tab?: string
        endpoint_name?: string
    }
    hashParams: {
        view?: string
        insight?: string
        draft?: string
        q?: string
    }
}

export interface EditorTabState {
    queryInput: string | null
    activeTab: QueryTab | null
}

export interface UrlIndicators {
    view: string | undefined
    insight: string | undefined
    draft: string | undefined
    query: string | undefined
}

export interface StateIndicators {
    hasView: boolean
    hasInsight: boolean
    hasDraft: boolean
}

/**
 * Extracts what entity type the URL is pointing to.
 * Checks both search params (open_*) and hash params.
 */
export function getUrlIndicators(params: UrlParams): UrlIndicators {
    const { searchParams, hashParams } = params
    return {
        view: searchParams.open_view || hashParams.view,
        insight: searchParams.open_insight || hashParams.insight,
        draft: searchParams.open_draft || hashParams.draft,
        query: searchParams.open_query || hashParams.q,
    }
}

/**
 * Extracts what entity type the current tab state has.
 */
export function getStateIndicators(state: EditorTabState): StateIndicators {
    return {
        hasView: !!state.activeTab?.view,
        hasInsight: !!state.activeTab?.insight,
        hasDraft: !!state.activeTab?.draft,
    }
}

/**
 * Determines if we need to reset the tab state.
 *
 * This handles the case where the URL no longer indicates a view/insight/draft
 * but our state still has one. For example, when navigating from
 * `/sql?view=123` to `/sql` - we need to clear the view from state.
 */
export function needsStateReset(urlIndicators: UrlIndicators, stateIndicators: StateIndicators): boolean {
    const urlHasNoView = !urlIndicators.view
    const urlHasNoInsight = !urlIndicators.insight
    const urlHasNoDraft = !urlIndicators.draft

    return (
        (urlHasNoView && stateIndicators.hasView) ||
        (urlHasNoInsight && stateIndicators.hasInsight) ||
        (urlHasNoDraft && stateIndicators.hasDraft)
    )
}

/**
 * Determines if we should skip processing this URL action.
 *
 * We skip when:
 * - The URL has no meaningful parameters to process
 * - We already have a query loaded (queryInput !== null)
 * - We don't need to reset state (no entity type mismatch)
 */
export function shouldSkipUrlAction(params: UrlParams, state: EditorTabState, needsReset: boolean): boolean {
    const { searchParams, hashParams } = params

    const urlHasNoParameters =
        !searchParams.open_query &&
        !searchParams.open_view &&
        !searchParams.open_insight &&
        !searchParams.open_draft &&
        !searchParams.output_tab &&
        !hashParams.q &&
        !hashParams.view &&
        !hashParams.insight

    const alreadyHasQuery = state.queryInput !== null

    return urlHasNoParameters && alreadyHasQuery && !needsReset
}

/**
 * Determines if we should open an entity from hash params.
 *
 * Hash params are used for state restoration (e.g., browser back/forward).
 * We only process them when:
 * - The hash param exists
 * - Either we have no query loaded yet, OR we need to reset state
 */
export function shouldOpenFromHashParams(
    hashValue: string | undefined,
    queryInput: string | null,
    needsReset: boolean
): boolean {
    return !!hashValue && (queryInput === null || needsReset)
}
