import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { HogQLQuery } from '~/queries/schema/schema-general'

// Relative ranges in day-or-coarser units ("mStart", "-7d") now snap to the start of the day,
// and open-ended ranges gain an end-of-today upper bound. Sub-day rolling windows ("-1h")
// were exempted from both, so they are not part of the affected shape.
const DAY_OR_COARSER_RELATIVE_REGEX = /^-?\d*[dwmqy](Start|End)?$/
const SUB_DAY_RELATIVE_REGEX = /^-?\d*[hMs](Start|End)?$/
const DATE_ONLY_REGEX = /^\d{4}-\d{1,2}-\d{1,2}$/

/** Whether the SQL date filter resolution fix can produce different results for this query.
 * Mirrors the affected shapes of ReplaceFilters in posthog/hogql/filters.py. */
export function isAffectedByDateFilterResolutionChange(source: HogQLQuery): boolean {
    if (!source.query?.includes('{filters')) {
        return false
    }
    const dateRange = source.filters?.dateRange
    if (!dateRange || (dateRange.date_from == null && dateRange.date_to == null)) {
        return false
    }
    // "all" stays fully unbounded (no lower bound and no end-of-today cap), so it is unaffected
    const openEndedWithBoundedStart =
        dateRange.date_to == null &&
        dateRange.date_from != null &&
        dateRange.date_from !== 'all' &&
        !SUB_DAY_RELATIVE_REGEX.test(dateRange.date_from)
    const snappedDateFrom = dateRange.date_from != null && DAY_OR_COARSER_RELATIVE_REGEX.test(dateRange.date_from)
    if (dateRange.explicitDate) {
        // explicitDate disables end-of-day snapping of date_to only; date_from still snaps to midnight
        return openEndedWithBoundedStart || snappedDateFrom
    }
    return (
        openEndedWithBoundedStart ||
        snappedDateFrom ||
        (dateRange.date_to != null &&
            (DATE_ONLY_REGEX.test(dateRange.date_to) || DAY_OR_COARSER_RELATIVE_REGEX.test(dateRange.date_to)))
    )
}

export function SqlInsightDateFilterNotice({ source }: { source: HogQLQuery }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (
        !featureFlags[FEATURE_FLAGS.SQL_INSIGHT_DATE_FILTER_NOTICE] ||
        !isAffectedByDateFilterResolutionChange(source)
    ) {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey="sql-insight-date-filter-notice">
            Date filters on SQL insights now match other insights: relative ranges start at midnight, and open-ended
            ranges include all of today but nothing after. Results may differ slightly from before.
        </LemonBanner>
    )
}
