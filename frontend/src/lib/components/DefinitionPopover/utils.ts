import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { allOperatorsInfo, genericOperatorInfo } from 'lib/utils'

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
    if (isPropertyFilterWithOperator(property) && property.operator && genericOperatorInfo[property.operator]) {
        return genericOperatorInfo[property.operator].label
    }
    return 'equals'
}

export function allOperatorsToHumanName(operator?: PropertyOperator | null): string {
    if (operator && allOperatorsInfo[operator]) {
        // for the case of cohort matching, we want to return the operator name without the "In" prefix
        if (operator === PropertyOperator.In) {
            return 'in'
        }
        return allOperatorsInfo[operator].label
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
            return 'attribute'
        case TaxonomicFilterGroupType.EventFeatureFlags:
            return 'feature'
        case TaxonomicFilterGroupType.PageviewUrls:
            return 'pageview url'
        case TaxonomicFilterGroupType.Screens:
            return 'screen'
        case TaxonomicFilterGroupType.Wildcards:
            return 'wildcard'
        default:
            return 'definition'
    }
}
