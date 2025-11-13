import { useValues } from 'kea'
import React from 'react'

import {
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
    formatPropertyLabel,
    isAnyPropertyfilter,
    isCohortPropertyFilter,
    isPropertyFilterWithOperator,
} from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/lemon-ui/Link'
import { allOperatorsMapping, capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    ActionFilter,
    FilterLogicalOperator,
    PropertyFilterBaseValue,
    PropertyGroupFilter,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

function isActionFilter(filter: UniversalFiltersGroupValue): filter is ActionFilter {
    return (filter as ActionFilter).type !== undefined && 'id' in filter
}

function isUniversalFiltersGroup(value: UniversalFiltersGroupValue): value is UniversalFiltersGroup {
    return (value as UniversalFiltersGroup).type !== undefined && (value as UniversalFiltersGroup).values !== undefined
}

export function CompactUniversalFiltersDisplay({
    groupFilter,
    embedded,
}: {
    groupFilter: UniversalFiltersGroup | PropertyGroupFilter | null
    embedded?: boolean
}): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    // Handle both UniversalFiltersGroup and PropertyGroupFilter
    const isPropertyGroupFilter =
        groupFilter &&
        'values' in groupFilter &&
        Array.isArray(groupFilter.values) &&
        groupFilter.values.length > 0 &&
        'values' in groupFilter.values[0]

    let filtersToRender: UniversalFiltersGroupValue[] = []
    let filterType = FilterLogicalOperator.And

    if (!groupFilter) {
        return <i>None</i>
    }

    if (isPropertyGroupFilter) {
        // PropertyGroupFilter has nested structure: { type, values: [{ type, values: [...] }] }
        const propertyGroup = groupFilter as PropertyGroupFilter
        filtersToRender = propertyGroup.values
        filterType = propertyGroup.type || FilterLogicalOperator.And
    } else {
        // UniversalFiltersGroup has flat structure: { type, values: [...] }
        const universalGroup = groupFilter as UniversalFiltersGroup
        filtersToRender = universalGroup.values
        filterType = universalGroup.type || FilterLogicalOperator.And
    }

    if (!filtersToRender.length) {
        return <i>None</i>
    }

    return (
        <>
            {filtersToRender.map((filterOrGroup, index) => {
                if (isUniversalFiltersGroup(filterOrGroup)) {
                    // Nested group
                    return (
                        <React.Fragment key={index}>
                            {index > 0 && (
                                <em className="text-[11px] font-semibold leading-5">
                                    {filterType === FilterLogicalOperator.Or ? 'OR' : 'AND'}
                                </em>
                            )}
                            <CompactUniversalFiltersDisplay groupFilter={filterOrGroup} embedded={embedded} />
                        </React.Fragment>
                    )
                }

                if (isActionFilter(filterOrGroup)) {
                    return (
                        <div key={index} className="SeriesDisplay__condition">
                            <span>
                                {embedded && index === 0 ? 'where ' : null}
                                {index > 0 ? (filterType === FilterLogicalOperator.Or ? 'or ' : 'and ') : null}
                                Performed action
                                <Link
                                    to={urls.action(filterOrGroup.id as number)}
                                    className="SeriesDisplay__raw-name SeriesDisplay__raw-name--action mx-1"
                                    title="Action"
                                >
                                    {filterOrGroup.name || `Action ${filterOrGroup.id}`}
                                </Link>
                            </span>
                        </div>
                    )
                }

                // Property filter
                const isFirstFilterOverall = index === 0

                return (
                    <div key={index} className="SeriesDisplay__condition">
                        <span>
                            {isFirstFilterOverall && embedded ? 'where ' : null}
                            {index > 0 ? (
                                <strong>{filterType === FilterLogicalOperator.Or ? 'or ' : 'and '}</strong>
                            ) : null}
                            {isCohortPropertyFilter(filterOrGroup) ? (
                                <>
                                    {isFirstFilterOverall && !embedded ? 'Person' : 'person'} belongs to cohort
                                    <span className="SeriesDisplay__raw-name">
                                        {formatPropertyLabel(
                                            filterOrGroup,
                                            cohortsById,
                                            (s) =>
                                                formatPropertyValueForDisplay(filterOrGroup.key, s)?.toString() || '?'
                                        )}
                                    </span>
                                </>
                            ) : (
                                <>
                                    {isFirstFilterOverall && !embedded
                                        ? capitalizeFirstLetter(filterOrGroup.type || 'event')
                                        : filterOrGroup.type || 'event'}
                                    's
                                    <span className="SeriesDisplay__raw-name">
                                        {isAnyPropertyfilter(filterOrGroup) && filterOrGroup.key && (
                                            <PropertyKeyInfo
                                                value={filterOrGroup.key}
                                                type={
                                                    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[
                                                        filterOrGroup.type
                                                    ]
                                                }
                                            />
                                        )}
                                    </span>
                                    <em>
                                        {
                                            allOperatorsMapping[
                                                (isPropertyFilterWithOperator(filterOrGroup) &&
                                                    filterOrGroup.operator) ||
                                                    'exact'
                                            ]
                                        }
                                    </em>{' '}
                                    {isAnyPropertyfilter(filterOrGroup) &&
                                        (Array.isArray(filterOrGroup.value) ? (
                                            filterOrGroup.value.map((subValue, index) => (
                                                <React.Fragment key={index}>
                                                    <code className="SeriesDisplay__value">{subValue}</code>
                                                    {index <
                                                        (filterOrGroup.value as PropertyFilterBaseValue[]).length - 1 &&
                                                        ' or '}
                                                </React.Fragment>
                                            ))
                                        ) : filterOrGroup.value != undefined ? (
                                            <code className="SeriesDisplay__value">{filterOrGroup.value}</code>
                                        ) : null)}
                                </>
                            )}
                        </span>
                    </div>
                )
            })}
        </>
    )
}
