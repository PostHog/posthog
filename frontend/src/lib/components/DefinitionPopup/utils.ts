import { PropertyFilterValue, PropertyOperator } from '~/types'
import { genericOperatorMap } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export function eventToHumanName(event?: string): string {
    return event && event[0] == '$' ? event[1].toUpperCase() + event.slice(2) : event ?? 'Event'
}

export function operatorToHumanName(operator?: string): string {
    if (operator === 'gte') {
        return 'at least'
    }
    if (operator === 'lte') {
        return 'at most'
    }
    return 'exactly'
}

export function genericOperatorToHumanName(operator?: PropertyOperator | null): string {
    if (operator && genericOperatorMap[operator]) {
        return genericOperatorMap[operator].slice(2)
    }
    return 'equals'
}

export function propertyValueToHumanName(value?: PropertyFilterValue): string {
    if (value?.[0]) {
        return value[0]
    }
    if (value === '') {
        return '(empty string)'
    }
    if (!value) {
        return String(value)
    }
    return ''
}

export function formatTimeFromNow(day?: string): string {
    return day ? dayjs.utc(day).fromNow() : '-'
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
            return 'property'
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
