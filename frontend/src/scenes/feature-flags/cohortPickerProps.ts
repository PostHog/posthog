import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyOperator } from '~/types'

/**
 * Picker props for cohort filters in feature flag release conditions and
 * workflow event triggers. Renders cohort rows as key-only (the cohort *is*
 * the value, operator is implicit). Both `in` and `not_in` are supported
 * by the backend, so neither is excluded here.
 *
 * Three call sites use this preset:
 * - `FeatureFlagReleaseConditions.tsx`
 * - `FeatureFlagReleaseConditionsCollapsible.tsx`
 * - `products/workflows/frontend/Workflows/hogflows/steps/StepTrigger.tsx`
 *
 * Spread into `PropertyFilters` / `TaxonomicPropertyFilter` rather than
 * passing each prop individually so the configuration travels as one named
 * idea and a future change edits one place.
 */
export const COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS = {
    excludedOperators: { [TaxonomicFilterGroupType.Cohorts]: [] as PropertyOperator[] },
    selectingKeyOnly: { [TaxonomicFilterGroupType.Cohorts]: true },
}
