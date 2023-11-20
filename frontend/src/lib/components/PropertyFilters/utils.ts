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
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    RecordingDurationFilter,
    SessionPropertyFilter,
} from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { flattenPropertyGroup, isPropertyGroup } from 'lib/utils'
import { BreakdownFilter } from '~/queries/schema'

/** Make sure unverified user property filter input has at least a "type" */
export function sanitizePropertyFilter(propertyFilter: AnyPropertyFilter): AnyPropertyFilter {
    if (!propertyFilter.type) {
        return {
            ...(propertyFilter as any), // TS error with spreading a union
            type: PropertyFilterType.Event,
        }
    }
    return propertyFilter
}

export function parseProperties(
    input: AnyPropertyFilter[] | PropertyGroupFilter | Record<string, any> | null | undefined
): AnyPropertyFilter[] {
    if (Array.isArray(input) || !input) {
        return input || []
    }
    if (input && !Array.isArray(input) && isPropertyGroup(input)) {
        return flattenPropertyGroup([], input)
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
export function isValidPropertyFilter(
    filter: AnyPropertyFilter | AnyFilterLike | Record<string, any>
): filter is AnyPropertyFilter {
    return (
        !!filter && // is not falsy
        'key' in filter && // has a "key" property
        ((filter.type === 'hogql' && !!filter.key) || Object.values(filter).some((v) => !!v)) // contains some properties with values
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
export function isEventPropertyOrPersonPropertyFilter(
    filter?: AnyFilterLike | null
): filter is EventPropertyFilter | PersonPropertyFilter {
    return filter?.type === PropertyFilterType.Event || filter?.type === PropertyFilterType.Person
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

const filterToTaxonomicFilterType = (
    type?: string | null,
    group_type_index?: number | null,
    value?: (string | number)[] | string | number | null
): TaxonomicFilterGroupType | undefined => {
    if (!type) {
        return undefined
    }
    if (type === 'group') {
        return `${TaxonomicFilterGroupType.GroupsPrefix}_${group_type_index}` as TaxonomicFilterGroupType
    }
    if (type === 'event' && typeof value === 'string' && value?.startsWith('$feature/')) {
        return TaxonomicFilterGroupType.EventFeatureFlags
    }
    return propertyFilterMapping[type]
}

export const propertyFilterTypeToTaxonomicFilterType = (
    filter: AnyPropertyFilter
): TaxonomicFilterGroupType | undefined =>
    filterToTaxonomicFilterType(filter.type, (filter as GroupPropertyFilter).group_type_index, filter.key)

export const breakdownFilterToTaxonomicFilterType = (
    breakdownFilter: BreakdownFilter
): TaxonomicFilterGroupType | undefined =>
    filterToTaxonomicFilterType(
        breakdownFilter.breakdown_type,
        breakdownFilter.breakdown_group_type_index,
        breakdownFilter.breakdown
    )

export function propertyFilterTypeToPropertyDefinitionType(
    filterType?: PropertyFilterType | string | null
): PropertyDefinitionType {
    return filterType === PropertyFilterType.Event
        ? PropertyDefinitionType.Event
        : filterType === PropertyFilterType.Person
        ? PropertyDefinitionType.Person
        : filterType === PropertyFilterType.Group
        ? PropertyDefinitionType.Group
        : PropertyDefinitionType.Event
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
