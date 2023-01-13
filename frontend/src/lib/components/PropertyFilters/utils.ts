import {
    AnyFilterLike,
    AnyPropertyFilter,
    CohortPropertyFilter,
    ElementPropertyFilter,
    EventDefinition,
    EventPropertyFilter,
    FeaturePropertyFilter,
    FilterLogicalOperator,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
    PropertyFilter,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    RecordingDurationFilter,
    SessionPropertyFilter,
} from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { flattenPropertyGroup, isPropertyGroup } from 'lib/utils'

/** Make sure unverified user property filter input has at least a "type" */
export function sanitizePropertyFilter(propertyFilter: AnyPropertyFilter): AnyPropertyFilter {
    if (!propertyFilter.type) {
        return {
            ...propertyFilter,
            type: PropertyFilterType.Event,
        }
    }
    return propertyFilter
}

export function parseProperties(
    input: AnyPropertyFilter[] | PropertyGroupFilter | Record<string, string> | null | undefined
): AnyPropertyFilter[] {
    if (Array.isArray(input) || !input) {
        return input || []
    }
    if (input && !Array.isArray(input) && isPropertyGroup(input)) {
        return flattenPropertyGroup([], input as PropertyGroupFilter)
    }
    // Old style dict properties
    return Object.entries(input).map(([inputKey, value]) => {
        const [key, operator] = inputKey.split('__')
        return {
            key,
            value,
            operator: operator as PropertyOperator,
            type: PropertyFilterType.Event,
        }
    })
}

/** Checks if the AnyPropertyFilter is a filled PropertyFilter */
export function isValidPropertyFilter(filter: AnyPropertyFilter): filter is PropertyFilter {
    return (
        !!filter && // is not falsy
        'key' in filter && // has a "key" property
        Object.values(filter).some((v) => !!v) // contains some properties with values
    )
}

export function isCohortPropertyFilter(filter?: AnyFilterLike | null): filter is CohortPropertyFilter {
    return filter?.type === PropertyFilterType.Cohort
}
export function isPropertyGroupFilterLike(
    filter?: AnyFilterLike | null
): filter is PropertyGroupFilter | PropertyGroupFilterValue {
    return filter?.type === FilterLogicalOperator.And || filter?.type === FilterLogicalOperator.Or
}
export function isEventPropertyFilter(filter?: AnyFilterLike | null): filter is EventPropertyFilter {
    return filter?.type === PropertyFilterType.Event
}
export function isPersonPropertyFilter(filter?: AnyFilterLike | null): filter is PersonPropertyFilter {
    return filter?.type === PropertyFilterType.Person
}
export function isElementPropertyFilter(filter?: AnyFilterLike | null): filter is ElementPropertyFilter {
    return filter?.type === PropertyFilterType.Element
}
export function isSessionPropertyFilter(filter?: AnyFilterLike | null): filter is SessionPropertyFilter {
    return filter?.type === PropertyFilterType.Session
}
export function isRecordingDurationFilter(filter?: AnyFilterLike | null): filter is RecordingDurationFilter {
    return filter?.type === PropertyFilterType.Recording
}
export function isGroupPropertyFilter(filter?: AnyFilterLike | null): filter is GroupPropertyFilter {
    return filter?.type === PropertyFilterType.Group
}
export function isFeaturePropertyFilter(filter?: AnyFilterLike | null): filter is FeaturePropertyFilter {
    return filter?.type === PropertyFilterType.Feature
}
export function isHogQLPropertyFilter(filter?: AnyFilterLike | null): filter is HogQLPropertyFilter {
    return filter?.type === PropertyFilterType.HogQL
}

export function isAnyPropertyfilter(filter?: AnyFilterLike | null): filter is AnyPropertyFilter {
    return (
        isEventPropertyFilter(filter) ||
        isPersonPropertyFilter(filter) ||
        isElementPropertyFilter(filter) ||
        isSessionPropertyFilter(filter) ||
        isCohortPropertyFilter(filter) ||
        isRecordingDurationFilter(filter) ||
        isFeaturePropertyFilter(filter) ||
        isGroupPropertyFilter(filter)
    )
}

export function isPropertyFilterWithOperator(
    filter?: AnyFilterLike | null
): filter is
    | EventPropertyFilter
    | PersonPropertyFilter
    | ElementPropertyFilter
    | SessionPropertyFilter
    | RecordingDurationFilter
    | FeaturePropertyFilter
    | GroupPropertyFilter {
    return (
        !isPropertyGroupFilterLike(filter) &&
        (isEventPropertyFilter(filter) ||
            isPersonPropertyFilter(filter) ||
            isElementPropertyFilter(filter) ||
            isSessionPropertyFilter(filter) ||
            isRecordingDurationFilter(filter) ||
            isFeaturePropertyFilter(filter) ||
            isGroupPropertyFilter(filter))
    )
}

export function isValidPathCleanFilter(filter: Record<string, any>): boolean {
    return filter.alias && filter.regex
}

export function filterMatchesItem(
    filter?: AnyPropertyFilter | null,
    item?: EventDefinition | null,
    itemType?: string
): boolean {
    if (!filter || !item || !itemType || filter.type !== itemType) {
        return false
    }
    return isCohortPropertyFilter(filter) ? filter.value === parseInt(item.id) : filter.key === item.name
}

const propertyFilterMapping: Partial<Record<PropertyFilterType, TaxonomicFilterGroupType>> = {
    [PropertyFilterType.Person]: TaxonomicFilterGroupType.PersonProperties,
    [PropertyFilterType.Event]: TaxonomicFilterGroupType.EventProperties,
    [PropertyFilterType.Feature]: TaxonomicFilterGroupType.EventFeatureFlags,
    [PropertyFilterType.Cohort]: TaxonomicFilterGroupType.Cohorts,
    [PropertyFilterType.Element]: TaxonomicFilterGroupType.Elements,
    [PropertyFilterType.Session]: TaxonomicFilterGroupType.Sessions,
    [PropertyFilterType.HogQL]: TaxonomicFilterGroupType.HogQLExpression,
}

export function propertyFilterTypeToTaxonomicFilterType(
    filterType?: string | null,
    groupTypeIndex?: number | null
): TaxonomicFilterGroupType | undefined {
    if (!filterType) {
        return undefined
    }
    if (filterType === 'group') {
        return `${TaxonomicFilterGroupType.GroupsPrefix}_${groupTypeIndex}` as TaxonomicFilterGroupType
    }
    return propertyFilterMapping[filterType]
}

export function taxonomicFilterTypeToPropertyFilterType(
    filterType?: TaxonomicFilterGroupType
): PropertyFilterType | undefined {
    if (filterType === TaxonomicFilterGroupType.CohortsWithAllUsers) {
        return PropertyFilterType.Cohort
    }
    if (filterType?.startsWith(TaxonomicFilterGroupType.GroupsPrefix)) {
        return PropertyFilterType.Group
    }

    if (filterType === TaxonomicFilterGroupType.EventFeatureFlags) {
        // Feature flags are just subgroup of event properties
        return PropertyFilterType.Event
    }

    return Object.entries(propertyFilterMapping).find(([, v]) => v === filterType)?.[0] as
        | PropertyFilterType
        | undefined
}
