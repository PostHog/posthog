import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

import { Node } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isHogQLQuery, isInsightVizNode } from '~/queries/utils'

/** Whether one insight's date range reaches past the team's events retention window.
 *
 * Shared by the per-insight banner and the dashboard-level banner so both surfaces answer this question the same way.
 * Works off the requested range rather than the range the backend resolved, so it holds before results load.
 */
export function exceedsRetention({
    query,
    dateFromOverride,
    retentionMonths,
}: {
    query?: Node | null
    /** Effective range from a surface that overrides the query's own: a dashboard or tile filter, or the live editor. */
    dateFromOverride?: string | null
    retentionMonths: number | null
}): boolean {
    if (!retentionMonths) {
        return false
    }

    const sqlSource = isHogQLQuery(query)
        ? query
        : isDataVisualizationNode(query) && isHogQLQuery(query.source)
          ? query.source
          : null
    // A SQL insight can scan arbitrary history and any date range it carries is inert unless the query interpolates
    // it, so there's no range here worth trusting. Warn whenever it reads events, which also keeps a `select 1` or
    // persons-only insight from warning forever.
    if (sqlSource) {
        return /\bevents\b/i.test(sqlSource.query ?? '')
    }

    const dateFrom = dateFromOverride ?? (isInsightVizNode(query) ? query.source?.dateRange?.date_from : undefined)
    if (!dateFrom) {
        return false
    }
    // "All time" is an unbounded intent: warn even when the team's data doesn't yet reach that far back.
    if (dateFrom === 'all') {
        return true
    }
    const resolved = dateStringToDayJs(dateFrom)
    return !!resolved && resolved.isBefore(dayjs().subtract(retentionMonths, 'month'))
}
