import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyOperator } from '~/types'

/**
 * Picker props for surfaces where cohort filters are restricted to `in` only.
 * Hides recents carrying any other cohort operator and renders cohort rows as
 * key-only (the cohort *is* the value, operator is implicit).
 *
 * Used by workflow event triggers (`StepTrigger.tsx`), which only support
 * cohort membership today.
 *
 * Spread into `PropertyFilters` / `TaxonomicPropertyFilter` rather than
 * passing each prop individually so the configuration travels as one named
 * idea.
 */
export const COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS = {
    excludedOperators: { [TaxonomicFilterGroupType.Cohorts]: [PropertyOperator.NotIn] },
    selectingKeyOnly: { [TaxonomicFilterGroupType.Cohorts]: true },
}

/**
 * Picker props for feature flag release conditions. Cohort rows render the
 * operator dropdown like any other property filter so users can pick `in` or
 * `not in` — the Rust flag-matching engine evaluates both. No restrictions,
 * but kept as a named preset so the two release-condition call sites share one
 * intent and the next change edits one place.
 *
 * Call sites:
 * - `FeatureFlagReleaseConditions.tsx`
 * - `FeatureFlagReleaseConditionsCollapsible.tsx`
 */
export const FEATURE_FLAG_COHORT_PICKER_PROPS = {}
