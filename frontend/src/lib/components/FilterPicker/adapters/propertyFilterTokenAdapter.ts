import { ReactNode } from 'react'

import {
    formatPropertyLabel,
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
} from 'lib/components/PropertyFilters/utils'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import {
    AnyPropertyFilter,
    CohortPropertyFilter,
    CohortType,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
} from '~/types'

import { FilterPickerToken, FilterPickerTokenPart } from '../FilterPicker.types'
import { operatorTokenLabel } from './propertyFilterOperatorAdapter'

export type FilterPickerValueFormatter = (
    value: PropertyFilterValue | undefined,
    filter: AnyPropertyFilter
) => ReactNode

export type FilterPickerPropertyLabelFormatter = (filter: AnyPropertyFilter) => ReactNode

function defaultValueFormatter(value: PropertyFilterValue | undefined): ReactNode {
    if (Array.isArray(value)) {
        return value.join(', ')
    }
    if (value === null || value === undefined) {
        return ''
    }
    return String(value)
}

function defaultPropertyLabel(filter: AnyPropertyFilter): ReactNode {
    if (filter.type === PropertyFilterType.Cohort) {
        return 'Cohort'
    }
    const label = 'label' in filter ? filter.label : undefined
    const taxonomicFilterGroupType = filter.type
        ? PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[filter.type]
        : undefined
    const coreLabel = taxonomicFilterGroupType
        ? getCoreFilterDefinition(filter.key, taxonomicFilterGroupType)?.label
        : undefined
    return coreLabel || label || filter.key
}

function propertyValue(
    filter: AnyPropertyFilter,
    cohortsById: Partial<Record<CohortType['id'], CohortType>>,
    valueFormatter: FilterPickerValueFormatter
): ReactNode {
    if (filter.type === PropertyFilterType.Cohort) {
        const cohortFilter = filter as CohortPropertyFilter
        const cohortId = typeof cohortFilter.value === 'number' ? cohortFilter.value : Number(cohortFilter.value)
        return cohortFilter.cohort_name || cohortsById[cohortId]?.name || `ID ${cohortFilter.value}`
    }
    return valueFormatter('value' in filter ? filter.value : undefined, filter)
}

function tokenTitle(
    filter: AnyPropertyFilter,
    cohortsById: Partial<Record<CohortType['id'], CohortType>>,
    valueFormatter: FilterPickerValueFormatter
): string {
    return formatPropertyLabel(filter, cohortsById, (value) => String(valueFormatter(value, filter)))
}

export interface CreatePropertyFilterTokenOptions {
    cohortsById?: Partial<Record<CohortType['id'], CohortType>>
    valueFormatter?: FilterPickerValueFormatter
    propertyLabelFormatter?: FilterPickerPropertyLabelFormatter
    editNodeIds?: string[]
    idSuffix?: string | number
    onRemove?: () => void
}

export function createPropertyFilterToken(
    filter: AnyPropertyFilter,
    options: CreatePropertyFilterTokenOptions = {}
): FilterPickerToken {
    const cohortsById = options.cohortsById ?? {}
    const valueFormatter = options.valueFormatter ?? defaultValueFormatter
    const propertyLabelFormatter = options.propertyLabelFormatter ?? defaultPropertyLabel
    const operator = 'operator' in filter ? (filter.operator as PropertyOperator) : PropertyOperator.Exact
    const parts: FilterPickerTokenPart[] = [
        {
            kind: 'property',
            label: propertyLabelFormatter(filter),
        },
        {
            kind: 'operator',
            label: operatorTokenLabel(operator),
        },
        {
            kind: 'value',
            label: propertyValue(filter, cohortsById, valueFormatter),
        },
    ]

    return {
        id: `${filter.type}:${filter.key}:${operator}:${String('value' in filter ? filter.value : '')}${
            options.idSuffix === undefined ? '' : `:${options.idSuffix}`
        }`,
        parts,
        title: tokenTitle(filter, cohortsById, valueFormatter),
        editPath: options.editNodeIds ? { nodeIds: options.editNodeIds } : undefined,
        removable: !!options.onRemove,
        editable: !!options.editNodeIds,
        onRemove: options.onRemove,
    }
}
