import { useActions } from 'kea'

import { useContinuousDwell } from 'lib/hooks/useContinuousDwell'
import { AnalysisEngagement, AnalysisSurface, analysisEngagementLogic } from 'lib/logic/analysisEngagementLogic'
import { hashCodeForString } from 'lib/utils/strings'

import { QueryContext } from '~/queries/types'

/**
 * Uninterrupted visible milliseconds before a rendered result counts as analyzed. Matches the
 * threshold the older `insight analyzed` event used, so the two are comparable, but here the time
 * has to be spent with the result actually on screen.
 */
export const ANALYSIS_ENGAGED_DWELL_MS = 10000

/**
 * Fraction of the result that must be inside the viewport to count as visible.
 *
 * This is a ratio of the element's own size, so a tall result reaches a lower maximum ratio than a
 * short one: an element four times the viewport height can never exceed 0.25. The value stays low
 * enough for those to qualify, while still excluding the case this gate exists for, which is a
 * dashboard tile that loads far below the fold and is never scrolled to.
 */
const ANALYSIS_ENGAGED_THRESHOLD = 0.25

/**
 * Resolves which surface rendered a result.
 *
 * An explicit `analysisSurface` wins, because only the host surface knows it. Everything else is
 * derived: PostHog AI marks its own queries with `limitContext`, and a tile carries the id of the
 * dashboard it sits on.
 */
export function resolveAnalysisSurface(
    context: QueryContext<any> | undefined,
    dashboardId: number | null | undefined
): AnalysisSurface {
    if (context?.analysisSurface) {
        return context.analysisSurface
    }
    if (context?.limitContext === 'posthog_ai') {
        return 'posthog_ai'
    }
    if (dashboardId != null) {
        return 'dashboard'
    }
    return 'insight'
}

/**
 * Builds the key that decides what counts once.
 *
 * A saved object keys on its short id, so returning to the same insight during one page visit
 * counts once. Anything unsaved keys on the query, so each distinct question a user asks counts
 * separately. An unsaved insight carries a placeholder short id that changes per mount, which would
 * make every render look like a new object, so those fall through to the query.
 */
export function analysisEngagementKey(shortId: string | undefined | null, query: unknown): string {
    if (shortId && !shortId.startsWith('new')) {
        return `insight:${shortId}`
    }
    return `query:${hashCodeForString(JSON.stringify(query) ?? '')}`
}

/**
 * Counts a rendered analytical result as engaged once the user has held it in view long enough to
 * read it. Pass `null` while the result is loading, errored, empty, or otherwise not worth
 * counting; nothing is observed and nothing fires until real content is on screen.
 *
 * Returns the ref callback to attach to the element that wraps the rendered result.
 */
export function useAnalysisEngagement(
    engagement: Omit<AnalysisEngagement, 'dwellMs'> | null
): (node?: Element | null) => void {
    const { reportAnalysisEngaged } = useActions(analysisEngagementLogic)

    return useContinuousDwell({
        active: engagement !== null,
        onDwell: () => {
            if (engagement) {
                reportAnalysisEngaged({ ...engagement, dwellMs: ANALYSIS_ENGAGED_DWELL_MS })
            }
        },
        dwellMs: ANALYSIS_ENGAGED_DWELL_MS,
        threshold: ANALYSIS_ENGAGED_THRESHOLD,
    })
}
