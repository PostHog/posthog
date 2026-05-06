import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyOperator } from '~/types'

/**
 * Picker props for surfaces where cohort filters are restricted to `in` only —
 * feature flag release conditions and workflow event triggers. Hides recents
 * carrying any other cohort operator and renders cohort rows as key-only
 * (the cohort *is* the value, operator is implicit).
 *
 * Three call sites use this preset:
 * - `FeatureFlagReleaseConditions.tsx`
 * - `FeatureFlagReleaseConditionsCollapsible.tsx`
 * - `products/workflows/frontend/Workflows/hogflows/steps/StepTrigger.tsx`
 *
 * Spread into `PropertyFilters` / `TaxonomicPropertyFilter` rather than
 * passing each prop individually so the configuration travels as one named
 * idea and a future change (e.g. allowing `not_in`) edits one place.
 */
export const COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS = {
    excludedOperators: { [TaxonomicFilterGroupType.Cohorts]: [PropertyOperator.NotIn] },
    selectingKeyOnly: { [TaxonomicFilterGroupType.Cohorts]: true },
}
