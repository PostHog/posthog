import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyOperator } from '~/types'

/**
 * Picker props for surfaces where cohort filters are restricted to `in` only —
 * workflow event triggers and heatmap filters. Hides recents carrying any other
 * cohort operator and renders cohort rows as key-only (the cohort *is* the value,
 * operator is implicit).
 *
 * Call sites using this preset:
 * - `products/workflows/frontend/Workflows/hogflows/steps/StepTrigger.tsx`
 * - `frontend/src/scenes/heatmaps/components/FilterPanel.tsx`
 *
 * Feature flag release conditions deliberately do NOT use this preset: flag
 * matching supports `not_in` cohorts (see the Rust cohort-membership evaluation
 * in `rust/feature-flags/src/cohorts/cohort_operations.rs`), so the flag UI
 * shows the full `user in` / `user not in` operator dropdown.
 *
 * Spread into `PropertyFilters` / `TaxonomicPropertyFilter` rather than passing
 * each prop individually so the configuration travels as one named idea.
 */
export const COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS = {
    excludedOperators: { [TaxonomicFilterGroupType.Cohorts]: [PropertyOperator.NotIn] },
    selectingKeyOnly: { [TaxonomicFilterGroupType.Cohorts]: true },
}
