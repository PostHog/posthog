import { isEmptyProperty, isFlagPropertyFilter } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter } from '~/types'

import { FLAG_DEPENDENCY_ESTIMATE_TOOLTIP, MATCHING_ESTIMATE_TOOLTIP } from './constants'

// The blast-radius estimate can't evaluate flag-dependency filters (they're resolved per
// user at serve time), so it treats them as matching everyone. These helpers let the UI
// detect that case and avoid showing a misleadingly large "Filters match" number.

/** Does this condition include a flag-dependency filter the blast-radius estimate can't evaluate? */
export function conditionHasFlagDependency(properties?: AnyPropertyFilter[] | null): boolean {
    return !!properties?.some(isFlagPropertyFilter)
}

/** Are all of a condition's non-empty filters flag dependencies? If so the estimate is just "everyone". */
export function conditionOnlyFlagDependencies(properties?: AnyPropertyFilter[] | null): boolean {
    const meaningful = (properties ?? []).filter((property) => !isEmptyProperty(property))
    return meaningful.length > 0 && meaningful.every(isFlagPropertyFilter)
}

/**
 * How to label the "Filters match" estimate. When a flag dependency is mixed with other filters the
 * estimate is an upper bound, so we prefix "at most" and swap in the flag-dependency tooltip.
 */
export function getEstimateLabelParts(properties?: AnyPropertyFilter[] | null): {
    hasFlagDependency: boolean
    atMostPrefix: string
    tooltip: JSX.Element
} {
    const hasFlagDependency = conditionHasFlagDependency(properties)
    return {
        hasFlagDependency,
        atMostPrefix: hasFlagDependency ? 'at most ' : '',
        tooltip: hasFlagDependency ? FLAG_DEPENDENCY_ESTIMATE_TOOLTIP : MATCHING_ESTIMATE_TOOLTIP,
    }
}
