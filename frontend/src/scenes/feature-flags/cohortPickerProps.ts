import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyOperator } from '~/types'

/**
 * Picker props for surfaces where cohort filters are restricted to `in` only.
 * Renders cohort rows as key-only (the cohort *is* the value, operator is
 * implicit) and hides recents carrying any other cohort operator.
 *
 * Used by workflow event triggers (`StepTrigger.tsx`), which only support
 * matching on cohort membership today.
 */
export const COHORTS_IN_ONLY_PICKER_PROPS = {
    excludedOperators: { [TaxonomicFilterGroupType.Cohorts]: [PropertyOperator.NotIn] },
    selectingKeyOnly: { [TaxonomicFilterGroupType.Cohorts]: true },
}

/**
 * Picker props for feature flag release conditions, which support both
 * `in cohort` and `not in cohort` matching. The operator dropdown stays
 * visible (no `selectingKeyOnly`) so users can choose between the two.
 *
 * Used by `FeatureFlagReleaseConditions.tsx` and
 * `FeatureFlagReleaseConditionsCollapsible.tsx`.
 */
export const FEATURE_FLAG_COHORT_PICKER_PROPS = {}
