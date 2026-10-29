import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    chooseOperatorMap,
    cohortOperatorMap,
    isOperatorDate,
    isOperatorFlag,
    isOperatorSemver,
    selectorOperatorMap,
} from 'lib/utils/operators'

import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { getFilterLabel } from '~/taxonomy/helpers'
import {
    AnyPropertyFilter,
    CohortPropertyFilter,
    CohortType,
    ElementPropertyFilter,
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    PropertyType,
} from '~/types'

import { categoryIdForFilter } from './filterBarCategories'
import {
    FilterBarCategoryId,
    FilterBarField,
    FilterBarOperatorOption,
    FilterBarValueKind,
    FilterBarItem,
} from './filterBarTypes'

const ELEMENT_KEYS: ElementPropertyFilter['key'][] = ['tag_name', 'text', 'href', 'selector']

export const ELEMENT_FIELDS: FilterBarField[] = ELEMENT_KEYS.map((key) => ({
    categoryId: 'elements',
    key,
    label: getFilterLabel(key, TaxonomicFilterGroupType.Elements),
    propertyType: key === 'selector' ? PropertyType.Selector : PropertyType.String,
}))

/**
 * The properties most filters start from, in the order they show. The web ones only show when the project
 * sends pageviews, and `email` only when people carry it, so a project never sees a property it cannot use.
 */
export const POPULAR_FIELDS: { categoryId: FilterBarCategoryId; key: string; needs?: 'pageview' | 'person_email' }[] = [
    { categoryId: 'event_properties', key: '$current_url', needs: 'pageview' },
    { categoryId: 'event_properties', key: '$pathname', needs: 'pageview' },
    { categoryId: 'event_properties', key: '$browser', needs: 'pageview' },
    { categoryId: 'event_properties', key: '$os' },
    { categoryId: 'event_properties', key: '$device_type' },
    { categoryId: 'event_properties', key: '$geoip_country_code' },
    { categoryId: 'person_properties', key: 'email', needs: 'person_email' },
    { categoryId: 'event_properties', key: '$referring_domain', needs: 'pageview' },
    { categoryId: 'event_properties', key: 'utm_source', needs: 'pageview' },
    { categoryId: 'session_properties', key: '$entry_pathname', needs: 'pageview' },
]

/** Operator labels read as a sentence after the field name: "Browser is Chrome", "Duration greater than 10". */
const OPERATOR_LABELS: Partial<Record<PropertyOperator, string>> = {
    [PropertyOperator.Exact]: 'is',
    [PropertyOperator.IsNot]: 'is not',
    [PropertyOperator.IContains]: 'contains',
    [PropertyOperator.NotIContains]: 'does not contain',
    [PropertyOperator.StartsWith]: 'starts with',
    [PropertyOperator.NotStartsWith]: 'does not start with',
    [PropertyOperator.EndsWith]: 'ends with',
    [PropertyOperator.NotEndsWith]: 'does not end with',
    [PropertyOperator.Regex]: 'matches regex',
    [PropertyOperator.NotRegex]: 'does not match regex',
    [PropertyOperator.GreaterThan]: 'greater than',
    [PropertyOperator.GreaterThanOrEqual]: 'at least',
    [PropertyOperator.LessThan]: 'less than',
    [PropertyOperator.LessThanOrEqual]: 'at most',
    [PropertyOperator.IsSet]: 'is set',
    [PropertyOperator.IsNotSet]: 'is not set',
    [PropertyOperator.IsDateExact]: 'is on',
    [PropertyOperator.IsDateBefore]: 'is before',
    [PropertyOperator.IsDateAfter]: 'is after',
    [PropertyOperator.In]: 'is',
    [PropertyOperator.NotIn]: 'is not',
}

const TAXONOMIC_GROUP_TYPE_BY_CATEGORY: Partial<Record<FilterBarCategoryId, TaxonomicFilterGroupType>> = {
    event_properties: TaxonomicFilterGroupType.EventProperties,
    person_properties: TaxonomicFilterGroupType.PersonProperties,
    session_properties: TaxonomicFilterGroupType.SessionProperties,
    feature_flags: TaxonomicFilterGroupType.EventFeatureFlags,
    elements: TaxonomicFilterGroupType.Elements,
}

export function taxonomicGroupTypeForCategory(categoryId: FilterBarCategoryId): TaxonomicFilterGroupType {
    if (categoryId.startsWith('group_properties_')) {
        return `${TaxonomicFilterGroupType.GroupsPrefix}_${categoryId.slice('group_properties_'.length)}` as TaxonomicFilterGroupType
    }
    return TAXONOMIC_GROUP_TYPE_BY_CATEGORY[categoryId] ?? TaxonomicFilterGroupType.EventProperties
}

export function propertyDefinitionTypeForCategory(categoryId: FilterBarCategoryId): PropertyDefinitionType {
    if (categoryId.startsWith('group_properties_')) {
        return PropertyDefinitionType.Group
    }
    switch (categoryId) {
        case 'person_properties':
            return PropertyDefinitionType.Person
        case 'session_properties':
            return PropertyDefinitionType.Session
        default:
            return PropertyDefinitionType.Event
    }
}

export function groupTypeIndexForCategory(categoryId: FilterBarCategoryId): number | undefined {
    return categoryId.startsWith('group_properties_') ? Number(categoryId.slice('group_properties_'.length)) : undefined
}

/** The human label of a property key: "Browser" for `$browser`, and the key itself when the taxonomy has no entry. */
export function fieldLabelForKey(categoryId: FilterBarCategoryId, key: string): string {
    if (categoryId === 'feature_flags') {
        return key.replace(/^\$feature\//, '')
    }
    return getFilterLabel(key, taxonomicGroupTypeForCategory(categoryId))
}

/** A cohort filter's field is "Cohort"; which cohort is its value, like any other filter. */
export function fieldFromFilter(filter: AnyPropertyFilter): FilterBarField | null {
    const categoryId = categoryIdForFilter(filter)
    if (!categoryId || !filter.key) {
        return null
    }
    if (categoryId === 'cohorts') {
        return { categoryId, key: 'id', label: 'Cohort' }
    }
    if (categoryId === 'sql') {
        return { categoryId, key: filter.key, label: extractExpressionComment(filter.key) }
    }
    return { categoryId, key: filter.key, label: fieldLabelForKey(categoryId, filter.key) }
}

const DEFAULT_OPERATOR_BY_KEY: Record<string, PropertyOperator> = {
    $current_url: PropertyOperator.IContains,
    $pathname: PropertyOperator.IContains,
    $active_feature_flags: PropertyOperator.IContains,
}

export function defaultOperatorForField(field: FilterBarField, propertyType?: PropertyType | null): PropertyOperator {
    if (field.categoryId === 'cohorts') {
        return PropertyOperator.In
    }
    if (DEFAULT_OPERATOR_BY_KEY[field.key]) {
        return DEFAULT_OPERATOR_BY_KEY[field.key]
    }
    switch (propertyType ?? field.propertyType) {
        case PropertyType.DateTime:
            return PropertyOperator.IsDateAfter
        case PropertyType.Duration:
            return PropertyOperator.GreaterThan
        default:
            return PropertyOperator.Exact
    }
}

/** A fresh filter for a field: complete for a cohort or SQL expression, and waiting for a value otherwise. */
export function newFilterForField(field: FilterBarField, propertyType?: PropertyType | null): AnyPropertyFilter {
    const operator = defaultOperatorForField(field, propertyType)
    switch (field.categoryId) {
        case 'cohorts':
            return {
                type: PropertyFilterType.Cohort,
                key: 'id',
                value: Number(field.key),
                operator,
                cohort_name: field.label,
            }
        case 'sql':
            return { type: PropertyFilterType.HogQL, key: field.key, value: null }
        case 'person_properties':
            return { type: PropertyFilterType.Person, key: field.key, operator, value: null }
        case 'session_properties':
            return { type: PropertyFilterType.Session, key: field.key, operator, value: null }
        case 'elements':
            return {
                type: PropertyFilterType.Element,
                key: field.key as ElementPropertyFilter['key'],
                operator,
                value: null,
            }
        default: {
            const groupTypeIndex = groupTypeIndexForCategory(field.categoryId)
            if (groupTypeIndex !== undefined) {
                return {
                    type: PropertyFilterType.Group,
                    key: field.key,
                    group_type_index: groupTypeIndex,
                    operator,
                    value: null,
                }
            }
            return { type: PropertyFilterType.Event, key: field.key, operator, value: null }
        }
    }
}

export function filterOperator(filter: AnyPropertyFilter): PropertyOperator | undefined {
    return 'operator' in filter ? filter.operator : undefined
}

/** The filter's values as the picker handles them. Booleans and bigints become strings, as the API sends them. */
export function filterValues(filter: AnyPropertyFilter): (string | number)[] {
    if (!('value' in filter) || filter.value == null || filter.value === '') {
        return []
    }
    const raw = Array.isArray(filter.value) ? filter.value : [filter.value]
    return raw.map((value) => (typeof value === 'number' ? value : String(value)))
}

/** Only complete filters reach the page and the URL. A field with no value yet stays in the bar as a pending chip. */
export function isFilterComplete(filter: AnyPropertyFilter): boolean {
    if (filter.type === PropertyFilterType.HogQL) {
        return !!filter.key
    }
    const operator = filterOperator(filter)
    if (operator && isOperatorFlag(operator)) {
        return filter.type !== PropertyFilterType.Cohort || typeof filter.value === 'number'
    }
    return filterValues(filter).length > 0
}

export function valueKindForFilter(filter: AnyPropertyFilter, propertyType?: PropertyType | null): FilterBarValueKind {
    if (filter.type === PropertyFilterType.Cohort) {
        return 'cohort'
    }
    if (filter.type === PropertyFilterType.HogQL) {
        return 'sql'
    }
    const operator = filterOperator(filter)
    if (operator && isOperatorFlag(operator)) {
        return 'none'
    }
    if ((operator && isOperatorDate(operator)) || propertyType === PropertyType.DateTime) {
        return 'date'
    }
    if (propertyType === PropertyType.Numeric || propertyType === PropertyType.Duration) {
        return 'number'
    }
    if (propertyType === PropertyType.Boolean) {
        return 'boolean'
    }
    return 'list'
}

function stripOperatorSymbol(label: string): string {
    return label.replace(/^[^\p{L}]+\s/u, '')
}

export function operatorOptionsForFilter(
    filter: AnyPropertyFilter,
    propertyType?: PropertyType | null
): FilterBarOperatorOption[] {
    let map: Record<string, string>
    if (filter.type === PropertyFilterType.Cohort) {
        map = cohortOperatorMap
    } else if (filter.type === PropertyFilterType.Element && filter.key === 'selector') {
        map = selectorOperatorMap
    } else {
        map = chooseOperatorMap(propertyType ?? undefined)
    }
    // Semver operators only matter for version strings, so they stay out of the list unless one is in use.
    const current = filterOperator(filter)
    const keepSemver = propertyType === PropertyType.Semver || (current && isOperatorSemver(current))
    return Object.entries(map)
        .filter(([value]) => keepSemver || !isOperatorSemver(value as PropertyOperator))
        .map(([value, label]) => ({
            value: value as PropertyOperator,
            label: OPERATOR_LABELS[value as PropertyOperator] ?? stripOperatorSymbol(label),
        }))
}

/** The operator as the chip shows it: "is" turns into "is any of" once the filter holds several values. */
export function operatorLabelForFilter(filter: AnyPropertyFilter): string {
    const operator = filterOperator(filter)
    if (!operator) {
        return ''
    }
    const count = filterValues(filter).length
    if (count > 1 && operator === PropertyOperator.Exact) {
        return 'is any of'
    }
    if (count > 1 && operator === PropertyOperator.IsNot) {
        return 'is none of'
    }
    return OPERATOR_LABELS[operator] ?? stripOperatorSymbol(chooseOperatorMap(undefined)[operator] ?? operator)
}

/** Lists keep every value the user ticks. Every other kind holds one value, so a new one replaces it. */
export function filterWithToggledValue(
    filter: AnyPropertyFilter,
    value: string | number,
    kind: FilterBarValueKind
): AnyPropertyFilter {
    if (!('value' in filter)) {
        return filter
    }
    if (kind !== 'list') {
        return { ...filter, value: value } as AnyPropertyFilter
    }
    const current = filterValues(filter).map(String)
    const next = current.includes(String(value))
        ? current.filter((v) => v !== String(value))
        : [...current, String(value)]
    return { ...filter, value: next } as AnyPropertyFilter
}

export function filterWithValue(filter: AnyPropertyFilter, value: PropertyFilterValue): AnyPropertyFilter {
    return { ...filter, value } as AnyPropertyFilter
}

/**
 * Changing the operator keeps the value when the new operator can use it. A flag operator such as "is set"
 * carries no value, and a range operator holds one number, so the old list does not survive those.
 */
export function filterWithOperator(filter: AnyPropertyFilter, operator: PropertyOperator): AnyPropertyFilter {
    if (!('operator' in filter)) {
        return filter
    }
    if (filter.type === PropertyFilterType.Cohort) {
        return { ...filter, operator } as AnyPropertyFilter
    }
    const values = filterValues(filter)
    let value: PropertyFilterValue = filter.value ?? null
    if (isOperatorFlag(operator)) {
        value = null
    } else if (values.length > 1 && operator !== PropertyOperator.Exact && operator !== PropertyOperator.IsNot) {
        value = [values[0]]
    } else if (isOperatorDate(operator) && values.length > 1) {
        value = values[0]
    }
    return { ...filter, operator, value } as AnyPropertyFilter
}

export function cohortNameForFilter(
    filter: CohortPropertyFilter,
    cohortsById: Partial<Record<CohortType['id'], CohortType>> = {}
): string {
    return filter.cohort_name || cohortsById[filter.value]?.name || `Cohort ${filter.value}`
}

/** The text of a chip's value segment, and whether that text stands in for a missing value. */
export function valueLabelForFilter(
    filter: AnyPropertyFilter,
    cohortsById: Partial<Record<CohortType['id'], CohortType>> = {},
    formatValue: (value: string | number) => string = String
): { text: string; placeholder: boolean } {
    if (filter.type === PropertyFilterType.HogQL) {
        return { text: filter.key, placeholder: false }
    }
    if (filter.type === PropertyFilterType.Cohort) {
        return { text: cohortNameForFilter(filter, cohortsById), placeholder: false }
    }
    const operator = filterOperator(filter)
    if (operator && isOperatorFlag(operator)) {
        return { text: '', placeholder: false }
    }
    const values = filterValues(filter)
    if (values.length === 0) {
        return { text: 'choose a value', placeholder: true }
    }
    const first = formatValue(values[0])
    return { text: values.length > 1 ? `${first}, +${values.length - 1}` : first, placeholder: false }
}

export function completeFilters(items: FilterBarItem[]): AnyPropertyFilter[] {
    return items.map((item) => item.filter).filter(isFilterComplete)
}
