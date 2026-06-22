import { createElement } from 'react'

import { TaxonomicDefinitionTypes, TaxonomicFilterGroup } from 'lib/components/TaxonomicFilter/types'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { AnyPropertyFilter, PropertyFilterType, PropertyFilterValue, PropertyOperator, PropertyType } from '~/types'

import {
    FilterPickerChildrenResult,
    FilterPickerNode,
    FilterPickerPanelContext,
    FilterPickerSelectContext,
} from '../FilterPicker.types'
import { FilterPickerDateValue } from './FilterPickerDateValue'
import {
    AUTO_ADVANCE_TYPES,
    createFilterPickerOperatorOptions,
    FilterPickerOperatorOption,
    resolveDefaultOperator,
} from './propertyFilterOperatorAdapter'

export interface FilterPickerPropertyOption {
    key: string
    label: string
    type: PropertyFilterType
    propertyType?: PropertyType
    description?: string
    section?: FilterPickerNode['section']
    taxonomicItem?: TaxonomicDefinitionTypes
    group?: TaxonomicFilterGroup
    /** Overrides the type's default operator (e.g. a String field that is really a version → semver). */
    defaultOperator?: PropertyOperator
    /** 'auto' skips the operator step and goes straight to value entry; 'pick' forces the operator list. */
    operatorMode?: 'auto' | 'pick'
}

export interface FilterPickerValueOption {
    value: PropertyFilterValue
    label: string
    description?: string
}

export interface PropertyValueLoaderResult {
    values: FilterPickerValueOption[]
    isLoading?: boolean
    hasMore?: boolean
    loadMore?: () => void
    isLoadingMore?: boolean
    allowCustomValues?: boolean
    /** Imperative trigger to fetch values for this property/query. Called from FilterPicker's content effect. */
    load?: () => void
}

export interface PropertyValueLoaderContext {
    property: FilterPickerPropertyOption
    operator: FilterPickerOperatorOption
    query: string
    eventNames?: string[]
}

export interface CreatePropertyFilterNodesOptions {
    properties: FilterPickerPropertyOption[]
    onSelect: (filter: AnyPropertyFilter, context: FilterPickerSelectContext) => void
    valueLoader?: (context: PropertyValueLoaderContext) => PropertyValueLoaderResult
    eventNames?: string[]
    operatorAllowlist?: Partial<Record<PropertyType, PropertyOperator[]>>
    rootSections?: Record<string, FilterPickerNode['section']>
}

function matchesQuery(text: string, query: string): boolean {
    return !query.trim() || text.toLowerCase().includes(query.trim().toLowerCase())
}

function nodeIdForProperty(property: FilterPickerPropertyOption): string {
    return `property:${property.type}:${property.key}`
}

function nodeIdForOperator(property: FilterPickerPropertyOption, operator: PropertyOperator): string {
    return `${nodeIdForProperty(property)}:operator:${operator}`
}

function nodeIdForValue(
    property: FilterPickerPropertyOption,
    operator: PropertyOperator,
    value: PropertyFilterValue
): string {
    return `${nodeIdForOperator(property, operator)}:value:${String(value)}`
}

function getDisplayLabel(property: FilterPickerPropertyOption): string {
    return property.group
        ? getCoreFilterDefinition(property.key, property.group.type)?.label || property.label || property.key
        : property.label || property.key
}

function createFilter(
    property: FilterPickerPropertyOption,
    operator: PropertyOperator,
    value: PropertyFilterValue
): AnyPropertyFilter {
    // AnyPropertyFilter is a discriminated union keyed on a literal `type`; this is a generic constructor
    // over the broad PropertyFilterType, so a single typed assertion (never `as any`) is the right tool.
    return {
        key: property.key,
        type: property.type,
        operator,
        value,
        group_type_index: property.group?.groupTypeIndex,
    } as AnyPropertyFilter
}

function DateValuePanel({
    property,
    operator,
    options,
    context,
}: {
    property: FilterPickerPropertyOption
    operator: FilterPickerOperatorOption
    options: CreatePropertyFilterNodesOptions
    context: FilterPickerPanelContext
}): JSX.Element {
    return createElement(FilterPickerDateValue, {
        onSelect: (isoDate: string) => {
            options.onSelect(createFilter(property, operator.operator, isoDate), context)
        },
    })
}

function valueNodes(
    property: FilterPickerPropertyOption,
    operator: FilterPickerOperatorOption,
    options: CreatePropertyFilterNodesOptions,
    query: string
): FilterPickerChildrenResult {
    const loaded = options.valueLoader?.({ property, operator, query, eventNames: options.eventNames })
    const values = loaded?.values ?? []
    const nodes = values
        .filter((value) => matchesQuery(value.label, query))
        .map<FilterPickerNode>((value) => ({
            id: nodeIdForValue(property, operator.operator, value.value),
            label: value.label,
            tokenLabel: value.label,
            description: value.description,
            kind: 'action',
            onSelect: (context) => options.onSelect(createFilter(property, operator.operator, value.value), context),
        }))

    if (loaded?.allowCustomValues && query.trim() && !values.some((value) => value.label === query.trim())) {
        nodes.unshift({
            id: nodeIdForValue(property, operator.operator, query.trim()),
            label: `Use "${query.trim()}"`,
            tokenLabel: query.trim(),
            kind: 'action',
            onSelect: (context) => options.onSelect(createFilter(property, operator.operator, query.trim()), context),
        })
    }

    return {
        nodes,
        isLoading: loaded?.isLoading,
        hasMore: loaded?.hasMore,
        loadMore: loaded?.loadMore,
        isLoadingMore: loaded?.isLoadingMore,
        emptyMessage: query ? 'No values found' : 'Start typing to search values',
    }
}

// The breadcrumb reads as a phrase ("Source contains"), so strip the leading symbol the menu label carries
// (e.g. "∋ contains" → "contains", "= equals" → "equals") while leaving symbol-free labels untouched.
function operatorBreadcrumbLabel(menuLabel: string): string {
    const [first, ...rest] = menuLabel.split(' ')
    return rest.length && !/[\p{L}\p{N}]/u.test(first) ? rest.join(' ') : menuLabel
}

// The picker commits a single value per filter. That matches every operator the string/datetime/cohort
// types expose; the multi-value `between`/`not between` operators are Numeric-only and are not added here
// unless a consumer's `operatorAllowlist` forces them, in which case they'd need a dedicated multi-value UI.
function operatorNode(
    property: FilterPickerPropertyOption,
    operator: FilterPickerOperatorOption,
    options: CreatePropertyFilterNodesOptions
): FilterPickerNode {
    if (!operator.metadata.acceptsValue) {
        return {
            id: nodeIdForOperator(property, operator.operator),
            label: operator.menuLabel,
            tokenLabel: operator.tokenLabel,
            breadcrumbLabel: operatorBreadcrumbLabel(operator.menuLabel),
            kind: 'action',
            onSelect: (context) => options.onSelect(createFilter(property, operator.operator, null), context),
        }
    }

    return {
        id: nodeIdForOperator(property, operator.operator),
        label: operator.menuLabel,
        tokenLabel: operator.tokenLabel,
        breadcrumbLabel: operatorBreadcrumbLabel(operator.menuLabel),
        kind: property.propertyType === PropertyType.DateTime ? 'panel' : 'branch',
        searchPlaceholder: 'Search or type a value…',
        getChildren:
            property.propertyType === PropertyType.DateTime
                ? undefined
                : ({ query }) => valueNodes(property, operator, options, query),
        loadContent:
            property.propertyType === PropertyType.DateTime
                ? undefined
                : ({ query }) =>
                      options.valueLoader?.({ property, operator, query, eventNames: options.eventNames }).load?.(),
        renderPanel:
            property.propertyType === PropertyType.DateTime
                ? (context) => createElement(DateValuePanel, { property, operator, options, context })
                : undefined,
    }
}

export function createPropertyFilterPickerNodes(options: CreatePropertyFilterNodesOptions): FilterPickerNode[] {
    return options.properties.map<FilterPickerNode>((property) => {
        const propertyType = property.propertyType ?? PropertyType.String
        const operatorAllowlist = options.operatorAllowlist?.[propertyType]
        const defaultOperator = resolveDefaultOperator(propertyType, property.defaultOperator)
        const operators = createFilterPickerOperatorOptions(propertyType, operatorAllowlist, defaultOperator)
        const label = getDisplayLabel(property)
        const section = property.section ?? options.rootSections?.[property.type]
        const searchableText = [label, property.key, property.type]

        // Skip the operator step for categories whose default operator dominates (or when only one exists).
        // The property node becomes the value step directly, with the operator implied in its breadcrumb.
        const autoAdvance =
            property.operatorMode === 'auto' ||
            (property.operatorMode !== 'pick' && (AUTO_ADVANCE_TYPES.has(propertyType) || operators.length === 1))

        if (autoAdvance && operators.length) {
            const operator = operators.find((option) => option.operator === defaultOperator) ?? operators[0]
            const valueStep = operatorNode(property, operator, options)
            return {
                ...valueStep,
                id: nodeIdForProperty(property),
                label,
                tokenLabel: label,
                // Operator is implicit when auto-advancing, so the breadcrumb is just the property label.
                breadcrumbLabel: label,
                description: property.description,
                section,
                searchableText,
            }
        }

        return {
            id: nodeIdForProperty(property),
            label,
            tokenLabel: label,
            description: property.description,
            kind: 'branch',
            section,
            searchableText,
            searchPlaceholder: 'Choose an operator…',
            getChildren: ({ query }) => ({
                nodes: operators
                    .filter((operator) => matchesQuery(operator.menuLabel, query))
                    .map((operator) => operatorNode(property, operator, options)),
                emptyMessage: 'No operators found',
            }),
        }
    })
}

export function editPathForPropertyFilter(filter: AnyPropertyFilter): string[] {
    const operator = 'operator' in filter ? filter.operator : PropertyOperator.Exact
    return [`property:${filter.type}:${filter.key}`, `property:${filter.type}:${filter.key}:operator:${operator}`]
}
