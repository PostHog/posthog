import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    allOperatorsMapping,
    capitalizeFirstLetter,
    cohortOperatorMap,
    isOperatorCohort,
    isOperatorFlag,
} from 'lib/utils'

import { propertyDefinitionsModelType } from '~/models/propertyDefinitionsModelType'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import {
    AnyFilterLike,
    AnyPropertyFilter,
    CohortPropertyFilter,
    CohortType,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    EventDefinition,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    FilterLogicalOperator,
    FlagPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    LogEntryPropertyFilter,
    LogPropertyFilter,
    PersonPropertyFilter,
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    PropertyType,
    RecordingPropertyFilter,
    RevenueAnalyticsPropertyFilter,
    SessionPropertyFilter,
} from '~/types'

export function isPropertyGroup(
    properties:
        | PropertyGroupFilter
        | PropertyGroupFilterValue
        | AnyPropertyFilter[]
        | AnyPropertyFilter
        | Record<string, any>
        | null
        | undefined
): properties is PropertyGroupFilter {
    return (
        (properties as PropertyGroupFilter)?.type !== undefined &&
        (properties as PropertyGroupFilter)?.values !== undefined
    )
}

function flattenPropertyGroup(
    flattenedProperties: AnyPropertyFilter[],
    propertyGroup: PropertyGroupFilter | PropertyGroupFilterValue | AnyPropertyFilter
): AnyPropertyFilter[] {
    const obj: AnyPropertyFilter = {} as EmptyPropertyFilter
    Object.keys(propertyGroup).forEach(function (k) {
        obj[k] = propertyGroup[k]
    })
    if (isValidPropertyFilter(obj)) {
        flattenedProperties.push(obj)
    }
    if (isPropertyGroup(propertyGroup)) {
        return propertyGroup.values.reduce(flattenPropertyGroup, flattenedProperties)
    }
    return flattenedProperties
}

export function convertPropertiesToPropertyGroup(
    properties: PropertyGroupFilter | AnyPropertyFilter[] | undefined | null
): PropertyGroupFilter {
    if (isPropertyGroup(properties)) {
        return properties
    }
    if (properties && properties.length > 0) {
        return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values: properties }] }
    }
    return { type: FilterLogicalOperator.And, values: [] }
}

/** Flatten a filter group into an array of filters. NB: Logical operators (AND/OR) are lost in the process. */
export function convertPropertyGroupToProperties(
    properties?: PropertyGroupFilter | AnyPropertyFilter[]
): AnyPropertyFilter[] | undefined {
    if (isPropertyGroup(properties)) {
        return flattenPropertyGroup([], properties).filter(isValidPropertyFilter)
    }
    if (properties) {
        return properties.filter(isValidPropertyFilter)
    }
    return properties
}

export const PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE: Record<PropertyFilterType, TaxonomicFilterGroupType> =
    {
        [PropertyFilterType.Meta]: TaxonomicFilterGroupType.Metadata,
        [PropertyFilterType.Person]: TaxonomicFilterGroupType.PersonProperties,
        [PropertyFilterType.Event]: TaxonomicFilterGroupType.EventProperties,
        [PropertyFilterType.EventMetadata]: TaxonomicFilterGroupType.EventMetadata,
        [PropertyFilterType.Feature]: TaxonomicFilterGroupType.EventFeatureFlags,
        [PropertyFilterType.Cohort]: TaxonomicFilterGroupType.Cohorts,
        [PropertyFilterType.Element]: TaxonomicFilterGroupType.Elements,
        [PropertyFilterType.Session]: TaxonomicFilterGroupType.SessionProperties,
        [PropertyFilterType.HogQL]: TaxonomicFilterGroupType.HogQLExpression,
        [PropertyFilterType.Group]: TaxonomicFilterGroupType.GroupsPrefix,
        [PropertyFilterType.DataWarehouse]: TaxonomicFilterGroupType.DataWarehouse,
        [PropertyFilterType.DataWarehousePersonProperty]: TaxonomicFilterGroupType.DataWarehousePersonProperties,
        [PropertyFilterType.Recording]: TaxonomicFilterGroupType.Replay,
        [PropertyFilterType.LogEntry]: TaxonomicFilterGroupType.LogEntries,
        [PropertyFilterType.ErrorTrackingIssue]: TaxonomicFilterGroupType.ErrorTrackingIssues,
        [PropertyFilterType.Log]: TaxonomicFilterGroupType.LogAttributes,
        [PropertyFilterType.RevenueAnalytics]: TaxonomicFilterGroupType.RevenueAnalyticsProperties,
        [PropertyFilterType.Flag]: TaxonomicFilterGroupType.FeatureFlags,
    }

export function formatPropertyLabel(
    item: Record<string, any>,
    cohortsById: Partial<Record<CohortType['id'], CohortType>>,
    valueFormatter: (value: PropertyFilterValue | undefined) => string | string[] | null = (s) => [String(s)]
): string {
    if (isHogQLPropertyFilter(item as AnyFilterLike)) {
        return extractExpressionComment(item.key)
    }
    const { value, key, operator, type, cohort_name, label } = item

    const taxonomicFilterGroupType = PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[type]

    return type === 'cohort'
        ? `${capitalizeFirstLetter(cohortOperatorMap[operator || 'in'] || 'user in')} ` +
              (cohort_name || cohortsById[value]?.name || `ID ${value}`)
        : (CORE_FILTER_DEFINITIONS_BY_GROUP[taxonomicFilterGroupType]?.[key]?.label || label || key) +
              (isOperatorFlag(operator)
                  ? ` ${allOperatorsMapping[operator]}`
                  : ` ${(allOperatorsMapping[operator || 'exact'] || '?').split(' ')[0]} ${
                        value && value.length === 1 && value[0] === '' ? '(empty string)' : valueFormatter(value) || ''
                    } `)
}

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
export function isEventMetadataPropertyFilter(filter?: AnyFilterLike | null): filter is EventMetadataPropertyFilter {
    return filter?.type === PropertyFilterType.EventMetadata
}
export function isRevenueAnalyticsPropertyFilter(
    filter?: AnyFilterLike | null
): filter is RevenueAnalyticsPropertyFilter {
    return filter?.type === PropertyFilterType.RevenueAnalytics
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
export function isEventPersonOrSessionPropertyFilter(
    filter?: AnyFilterLike | null
): filter is EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter {
    return (
        filter?.type === PropertyFilterType.Event ||
        filter?.type === PropertyFilterType.Person ||
        filter?.type === PropertyFilterType.Session
    )
}
export function isElementPropertyFilter(filter?: AnyFilterLike | null): filter is ElementPropertyFilter {
    return filter?.type === PropertyFilterType.Element
}
export function isSessionPropertyFilter(filter?: AnyFilterLike | null): filter is SessionPropertyFilter {
    return filter?.type === PropertyFilterType.Session
}
export function isRecordingPropertyFilter(filter?: AnyFilterLike | null): filter is RecordingPropertyFilter {
    return filter?.type === PropertyFilterType.Recording
}
export function isLogEntryPropertyFilter(filter?: AnyFilterLike | null): filter is LogEntryPropertyFilter {
    return filter?.type === PropertyFilterType.LogEntry
}
export function isGroupPropertyFilter(filter?: AnyFilterLike | null): filter is GroupPropertyFilter {
    return filter?.type === PropertyFilterType.Group
}
export function isLogPropertyFilter(filter?: AnyFilterLike | null): filter is LogPropertyFilter {
    return filter?.type === PropertyFilterType.Log
}
export function isErrorTrackingIssuePropertyFilter(filter?: AnyFilterLike | null): filter is GroupPropertyFilter {
    return filter?.type === PropertyFilterType.ErrorTrackingIssue
}
export function isDataWarehousePropertyFilter(filter?: AnyFilterLike | null): filter is DataWarehousePropertyFilter {
    return filter?.type === PropertyFilterType.DataWarehouse
}
export function isDataWarehousePersonPropertyFilter(
    filter?: AnyFilterLike | null
): filter is DataWarehousePropertyFilter {
    return filter?.type === PropertyFilterType.DataWarehousePersonProperty
}
export function isFeaturePropertyFilter(filter?: AnyFilterLike | null): filter is FeaturePropertyFilter {
    return filter?.type === PropertyFilterType.Feature
}
export function isFlagPropertyFilter(filter?: AnyFilterLike | null): filter is FlagPropertyFilter {
    return filter?.type === PropertyFilterType.Flag
}
export function isHogQLPropertyFilter(filter?: AnyFilterLike | null): filter is HogQLPropertyFilter {
    return filter?.type === PropertyFilterType.HogQL
}

export function isAnyPropertyfilter(filter?: AnyFilterLike | null): filter is AnyPropertyFilter {
    return (
        isEventPropertyFilter(filter) ||
        isPersonPropertyFilter(filter) ||
        isEventMetadataPropertyFilter(filter) ||
        isRevenueAnalyticsPropertyFilter(filter) ||
        isElementPropertyFilter(filter) ||
        isSessionPropertyFilter(filter) ||
        isCohortPropertyFilter(filter) ||
        isRecordingPropertyFilter(filter) ||
        isLogEntryPropertyFilter(filter) ||
        isFeaturePropertyFilter(filter) ||
        isFlagPropertyFilter(filter) ||
        isGroupPropertyFilter(filter) ||
        isLogPropertyFilter(filter)
    )
}

export function isPropertyFilterWithOperator(
    filter?: AnyFilterLike | null
): filter is
    | EventPropertyFilter
    | PersonPropertyFilter
    | EventMetadataPropertyFilter
    | RevenueAnalyticsPropertyFilter
    | ElementPropertyFilter
    | SessionPropertyFilter
    | RecordingPropertyFilter
    | LogEntryPropertyFilter
    | FeaturePropertyFilter
    | GroupPropertyFilter
    | DataWarehousePropertyFilter
    | DataWarehousePersonPropertyFilter {
    return (
        !isPropertyGroupFilterLike(filter) &&
        (isEventPropertyFilter(filter) ||
            isPersonPropertyFilter(filter) ||
            isEventMetadataPropertyFilter(filter) ||
            isRevenueAnalyticsPropertyFilter(filter) ||
            isElementPropertyFilter(filter) ||
            isSessionPropertyFilter(filter) ||
            isRecordingPropertyFilter(filter) ||
            isLogEntryPropertyFilter(filter) ||
            isFeaturePropertyFilter(filter) ||
            isFlagPropertyFilter(filter) ||
            isGroupPropertyFilter(filter) ||
            isCohortPropertyFilter(filter) ||
            isDataWarehousePropertyFilter(filter) ||
            isDataWarehousePersonPropertyFilter(filter) ||
            isErrorTrackingIssuePropertyFilter(filter))
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
    [PropertyFilterType.EventMetadata]: TaxonomicFilterGroupType.EventMetadata,
    [PropertyFilterType.Cohort]: TaxonomicFilterGroupType.Cohorts,
    [PropertyFilterType.Element]: TaxonomicFilterGroupType.Elements,
    [PropertyFilterType.Session]: TaxonomicFilterGroupType.SessionProperties,
    [PropertyFilterType.HogQL]: TaxonomicFilterGroupType.HogQLExpression,
    [PropertyFilterType.Recording]: TaxonomicFilterGroupType.Replay,
    [PropertyFilterType.ErrorTrackingIssue]: TaxonomicFilterGroupType.ErrorTrackingIssues,
    [PropertyFilterType.Log]: TaxonomicFilterGroupType.LogAttributes,
    [PropertyFilterType.RevenueAnalytics]: TaxonomicFilterGroupType.RevenueAnalyticsProperties,
    [PropertyFilterType.Flag]: TaxonomicFilterGroupType.FeatureFlags,
}

export const filterToTaxonomicFilterType = (
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
    const mapping: { [key in PropertyFilterType]?: PropertyDefinitionType } = {
        [PropertyFilterType.Event]: PropertyDefinitionType.Event,
        [PropertyFilterType.EventMetadata]: PropertyDefinitionType.EventMetadata,
        [PropertyFilterType.Person]: PropertyDefinitionType.Person,
        [PropertyFilterType.Group]: PropertyDefinitionType.Group,
        [PropertyFilterType.Session]: PropertyDefinitionType.Session,
        [PropertyFilterType.Recording]: PropertyDefinitionType.Session,
        [PropertyFilterType.LogEntry]: PropertyDefinitionType.LogEntry,
        [PropertyFilterType.ErrorTrackingIssue]: PropertyDefinitionType.Resource,
        [PropertyFilterType.Log]: PropertyDefinitionType.Log,
        [PropertyFilterType.RevenueAnalytics]: PropertyDefinitionType.RevenueAnalytics,
        [PropertyFilterType.Flag]: PropertyDefinitionType.FlagValue,
    }

    return mapping[filterType as PropertyFilterType] ?? PropertyDefinitionType.Event
}

export function taxonomicFilterTypeToPropertyFilterType(
    filterType?: TaxonomicFilterGroupType
): PropertyFilterType | undefined {
    if (filterType === TaxonomicFilterGroupType.CohortsWithAllUsers) {
        return PropertyFilterType.Cohort
    }
    if (filterType === TaxonomicFilterGroupType.EventMetadata) {
        return PropertyFilterType.EventMetadata
    }
    if (
        filterType?.startsWith(TaxonomicFilterGroupType.GroupsPrefix) ||
        filterType?.startsWith(TaxonomicFilterGroupType.GroupNamesPrefix)
    ) {
        return PropertyFilterType.Group
    }

    if (filterType === TaxonomicFilterGroupType.EventFeatureFlags) {
        // Feature flags are just subgroup of event properties
        return PropertyFilterType.Event
    }

    if (filterType == TaxonomicFilterGroupType.DataWarehouseProperties) {
        return PropertyFilterType.DataWarehouse
    }

    if (filterType == TaxonomicFilterGroupType.DataWarehousePersonProperties) {
        return PropertyFilterType.DataWarehousePersonProperty
    }

    if (filterType == TaxonomicFilterGroupType.ErrorTrackingIssues) {
        return PropertyFilterType.ErrorTrackingIssue
    }

    if (filterType === TaxonomicFilterGroupType.FeatureFlags) {
        // Feature flags dependencies (flag + value) as a property filter
        return PropertyFilterType.Flag
    }

    if (filterType == TaxonomicFilterGroupType.LogAttributes) {
        return PropertyFilterType.Log
    }

    if (filterType == TaxonomicFilterGroupType.RevenueAnalyticsProperties) {
        return PropertyFilterType.RevenueAnalytics
    }

    return Object.entries(propertyFilterMapping).find(([, v]) => v === filterType)?.[0] as
        | PropertyFilterType
        | undefined
}

export function isEmptyProperty(property: AnyPropertyFilter): boolean {
    return (
        property.value === null ||
        property.value === undefined ||
        (Array.isArray(property.value) && property.value.length === 0)
    )
}

export function createDefaultPropertyFilter(
    filter: AnyPropertyFilter | null,
    propertyKey: string | number,
    propertyType: PropertyFilterType,
    taxonomicGroup: TaxonomicFilterGroup,
    describeProperty: propertyDefinitionsModelType['values']['describeProperty'],
    originalQuery?: string
): AnyPropertyFilter {
    if (propertyType === PropertyFilterType.Cohort) {
        const operator =
            (isPropertyFilterWithOperator(filter) && isOperatorCohort(filter?.operator) && filter?.operator) ||
            PropertyOperator.In
        const cohortProperty: CohortPropertyFilter = {
            key: 'id',
            value: parseInt(String(propertyKey)),
            type: propertyType,
            operator: operator,
        }
        return cohortProperty
    }

    if (propertyType === PropertyFilterType.HogQL) {
        const hogQLProperty: HogQLPropertyFilter = {
            type: propertyType,
            key: String(propertyKey),
            value: null, // must specify something to be compatible with existing types
        }
        return hogQLProperty
    }

    if (propertyType === PropertyFilterType.Flag) {
        const flagProperty: FlagPropertyFilter = {
            type: propertyType,
            key: String(propertyKey),
            value: true, // Default to true
            operator: PropertyOperator.FlagEvaluatesTo,
        }
        return flagProperty
    }

    const apiType = propertyFilterTypeToPropertyDefinitionType(propertyType) ?? PropertyDefinitionType.Event

    const propertyValueType = describeProperty(propertyKey, apiType, taxonomicGroup.groupTypeIndex)
    const property_name_to_default_operator_override = {
        $active_feature_flags: PropertyOperator.IContains,
    }
    const property_value_type_to_default_operator_override = {
        [PropertyType.Duration]: PropertyOperator.GreaterThan,
        [PropertyType.DateTime]: PropertyOperator.IsDateExact,
        [PropertyType.Selector]: PropertyOperator.Exact,
    }
    const operator =
        property_name_to_default_operator_override[propertyKey] ||
        (isPropertyFilterWithOperator(filter) && !isOperatorCohort(filter.operator) ? filter.operator : null) ||
        property_value_type_to_default_operator_override[propertyValueType ?? ''] ||
        PropertyOperator.Exact

    const isGroupNameFilter = taxonomicGroup.type.startsWith(TaxonomicFilterGroupType.GroupNamesPrefix)
    // :TRICKY: When we have a GroupNamesPrefix taxonomic filter, selecting the group name
    // is the equivalent of selecting a property value
    const property: AnyPropertyFilter = {
        key: isGroupNameFilter ? '$group_key' : propertyKey.toString(),
        value: isGroupNameFilter ? propertyKey.toString() : (originalQuery ?? null),
        operator,
        type: propertyType as AnyPropertyFilter['type'] as any, // bad | pipe chain :(
        group_type_index: taxonomicGroup.groupTypeIndex,
    }
    return property
}
