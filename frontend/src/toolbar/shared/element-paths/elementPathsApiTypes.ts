/**
 * The shapes of the user journeys element paths endpoint, for the toolbar.
 *
 * The generated types live in `products/user_journeys/frontend/generated/`, and the toolbar may not import from
 * `products/` (the `no-restricted-imports` rule for `frontend/src/toolbar`). These mirror
 * `ElementPathsQuerySerializer`, `ElementPathsResultSerializer` and the journey step serializers in
 * `products/user_journeys/backend/presentation/`. `elementPaths.test.ts` fails to type-check when they stop matching
 * the generated types, so update them when those serializers change.
 */

export type UrlMatching = 'exact' | 'contains' | 'regex'

export type JourneySource = 'toolbar' | 'manual'

export interface PageviewStep {
    type: 'pageview'
    url: string
    url_matching?: UrlMatching
}

export interface ElementClickStep {
    type: 'element_click'
    selector: string
    text?: string | null
    href?: string | null
    url?: string | null
    url_matching?: UrlMatching
}

export type JourneyStep = PageviewStep | ElementClickStep

export interface ElementPathNode {
    step: JourneyStep
    label: string
    is_anchor: boolean
    /** False when `step` is a best-effort match for the events this node counts. */
    step_is_exact: boolean
}

export interface ElementPath {
    nodes: ElementPathNode[]
    session_count: number
    /** From 0 to 1. */
    share_of_anchor_sessions: number
    anchor_index: number
}

export interface ElementPathsResult {
    paths: ElementPath[]
    date_from: string
    date_to: string
    /** Zero means nobody clicked the element in the range. */
    anchor_click_count: number
    anchor_session_count: number
    analyzed_session_count: number
}

export interface ElementPathsParams {
    selector: string
    text?: string
    href?: string
    url?: string
    url_matching?: UrlMatching
    date_from?: string
    date_to?: string
    steps_before?: number
    steps_after?: number
    limit?: number
    filter_test_accounts?: boolean
}
