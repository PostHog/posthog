import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { allOperatorsMapping, genericOperatorMap } from 'lib/utils/operators'

import { AnyPropertyFilter, PropertyFilterValue, PropertyOperator } from '~/types'

export function operatorToHumanName(operator?: string): string {
    if (operator === 'gte') {
        return 'at least'
    }
    if (operator === 'lte') {
        return 'at most'
    }
    return 'exactly'
}

export function genericOperatorToHumanName(property?: AnyPropertyFilter | null): string {
    // Legacy action step properties have no `type`, so isPropertyFilterWithOperator would reject them
    // and collapse every operator to "equals" — read the operator directly instead. Prefer the curated
    // generic labels, but fall back to the full operator map (covers semver etc.) rather than a
    // hardcoded "equals" for anything outside the generic subset.
    const operator = property && 'operator' in property ? property.operator : undefined
    if (operator && genericOperatorMap[operator]) {
        return genericOperatorMap[operator].slice(2)
    }
    return allOperatorsToHumanName(operator)
}

// Most operator labels carry a 2-char "<symbol> " prefix that slice(2) strips (e.g. "= equals"
// -> "equals"). Cohort operators are stored without that prefix ("user in" / "user not in"), so
// slicing would mangle them. Any future prefix-less label must be added here too.
const prefixlessOperatorLabels: Partial<Record<PropertyOperator, string>> = {
    [PropertyOperator.In]: 'in',
    [PropertyOperator.NotIn]: 'not in',
}

export function allOperatorsToHumanName(operator?: PropertyOperator | null): string {
    if (operator && prefixlessOperatorLabels[operator]) {
        return prefixlessOperatorLabels[operator]
    }
    if (operator && allOperatorsMapping[operator]) {
        return allOperatorsMapping[operator].slice(2)
    }
    return 'equals'
}

export function propertyValueToHumanName(value?: PropertyFilterValue): string {
    const values = Array.isArray(value) ? value : [value]
    return values.map((value) => (value === '' ? '(empty string)' : String(value))).join(' or ')
}

export function getSingularType(type: TaxonomicFilterGroupType): string {
    switch (type) {
        case TaxonomicFilterGroupType.Actions:
            return 'action'
        case TaxonomicFilterGroupType.Cohorts:
        case TaxonomicFilterGroupType.CohortsWithAllUsers:
            return 'cohort'
        case TaxonomicFilterGroupType.Elements:
            return 'element'
        case TaxonomicFilterGroupType.Events:
        case TaxonomicFilterGroupType.CustomEvents:
            return 'event'
        case TaxonomicFilterGroupType.EventProperties:
        case TaxonomicFilterGroupType.PersonProperties:
        case TaxonomicFilterGroupType.GroupsPrefix: // Group properties
        case TaxonomicFilterGroupType.SessionProperties:
            return 'property'
        case TaxonomicFilterGroupType.LogAttributes:
        case TaxonomicFilterGroupType.MetricAttributes:
            return 'attribute'
        case TaxonomicFilterGroupType.EventFeatureFlags:
            return 'feature'
        case TaxonomicFilterGroupType.PageviewUrls:
            return 'pageview url'
        case TaxonomicFilterGroupType.PageviewEvents:
            return 'pageview event'
        case TaxonomicFilterGroupType.Screens:
            return 'screen'
        case TaxonomicFilterGroupType.ScreenEvents:
            return 'screen event'
        case TaxonomicFilterGroupType.EmailAddresses:
            return 'email address'
        case TaxonomicFilterGroupType.AutocaptureEvents:
            return 'autocapture event'
        case TaxonomicFilterGroupType.Wildcards:
            return 'wildcard'
        default:
            return 'definition'
    }
}
