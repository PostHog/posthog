import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { isActionFilter, isEventFilter } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { deriveOperand } from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'

import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyOperator,
    RecordingUniversalFilters,
    UniversalFilterValue,
} from '~/types'

// Mirrors NEGATIVE_OPERATORS in posthog/session_recordings/queries/utils.py, plus the cohort
// `not_in` operator that the backend routes to the blocklist by its own check.
const NEGATIVE_OPERATORS: ReadonlySet<string> = new Set([
    PropertyOperator.IsNotSet,
    PropertyOperator.IsNot,
    PropertyOperator.NotRegex,
    PropertyOperator.NotIContains,
    PropertyOperator.NotStartsWith,
    PropertyOperator.NotEndsWith,
    PropertyOperator.NotIn,
])

function hasNegativeOperator(filter: AnyPropertyFilter): boolean {
    return 'operator' in filter && NEGATIVE_OPERATORS.has(filter.operator ?? '')
}

function isNegativeFilter(filter: UniversalFilterValue): boolean {
    if (isEventFilter(filter) || isActionFilter(filter)) {
        return !!filter.negation || (filter.properties ?? []).some(hasNegativeOperator)
    }
    return hasNegativeOperator(filter)
}

/** Whether applying negative filters as exclusions under OR can change this list's results.
 * Mirrors the gate in ReplayFiltersEventsSubQuery._or_exclusions_enabled in
 * posthog/session_recordings/queries/sub_queries/events_subquery.py: operand OR and at least one
 * negative filter. */
export function isAffectedByReplayExclusionsUnderOrChange(filters: RecordingUniversalFilters): boolean {
    if (deriveOperand(filters.filter_group) !== FilterLogicalOperator.Or) {
        return false
    }
    return filtersFromUniversalFilterGroups(filters).some(isNegativeFilter)
}

// Remove after 2026-12-18, once affected users have had a full quarter to see it.
export function ReplayExclusionsUnderOrNotice({ filters }: { filters: RecordingUniversalFilters }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (
        !featureFlags[FEATURE_FLAGS.REPLAY_EXCLUSIONS_UNDER_OR_NOTICE] ||
        !featureFlags[FEATURE_FLAGS.REPLAY_EXCLUSIONS_UNDER_OR] ||
        !isAffectedByReplayExclusionsUnderOrChange(filters)
    ) {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey="replay-exclusions-under-or-notice" className="m-2">
            When you match any filter, filters such as "is not set" and "doesn't contain" now remove recordings instead
            of matching them. This list may show fewer recordings than before.
        </LemonBanner>
    )
}
