import { useValues } from 'kea'
import React from 'react'

import { IconClock, IconFilter, IconSort } from '@posthog/icons'

import {
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
    formatPropertyLabel,
    isAnyPropertyfilter,
    isCohortPropertyFilter,
    isPropertyFilterWithOperator,
} from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { allOperatorsMapping, capitalizeFirstLetter } from 'lib/utils'
import { humanFriendlyDurationFilter } from 'scenes/session-recordings/filters/DurationFilter'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    ActionFilter,
    AnyPropertyFilter,
    DurationType,
    FilterLogicalOperator,
    PropertyFilterBaseValue,
    PropertyGroupFilter,
    RecordingUniversalFilters,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { DateRangeSummary, InsightDetailSectionDisplay } from './InsightDetails'

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
                                <span className="text-[11px] font-semibold leading-5">
                                    {filterType === FilterLogicalOperator.Or ? 'OR' : 'AND'}
                                </span>
                            )}
                            <CompactUniversalFiltersDisplay groupFilter={filterOrGroup} embedded={embedded} />
                        </React.Fragment>
                    )
                }

                if (isActionFilter(filterOrGroup)) {
                    // Action filter
                    return (
                        <React.Fragment key={index}>
                            <div className="SeriesDisplay__condition">
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
                        </React.Fragment>
                    )
                }

                // Property filter
                const leafFilter = filterOrGroup as AnyPropertyFilter
                const isFirstFilterOverall = index === 0

                return (
                    <React.Fragment key={index}>
                        <div className="SeriesDisplay__condition">
                            <span>
                                {isFirstFilterOverall && embedded ? 'where ' : null}
                                {index > 0 ? (
                                    <strong>{filterType === FilterLogicalOperator.Or ? <em>or </em> : 'and '}</strong>
                                ) : null}
                                {isCohortPropertyFilter(leafFilter) ? (
                                    <>
                                        {isFirstFilterOverall && !embedded ? 'Person' : 'person'} belongs to cohort
                                        <span className="SeriesDisplay__raw-name">
                                            {formatPropertyLabel(
                                                leafFilter,
                                                cohortsById,
                                                (s) =>
                                                    formatPropertyValueForDisplay(leafFilter.key, s)?.toString() || '?'
                                            )}
                                        </span>
                                    </>
                                ) : (
                                    <>
                                        {isFirstFilterOverall && !embedded
                                            ? capitalizeFirstLetter(leafFilter.type || 'event')
                                            : leafFilter.type || 'event'}
                                        's
                                        <span className="SeriesDisplay__raw-name">
                                            {isAnyPropertyfilter(leafFilter) && leafFilter.key && (
                                                <PropertyKeyInfo
                                                    value={leafFilter.key}
                                                    type={
                                                        PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[
                                                            leafFilter.type
                                                        ]
                                                    }
                                                />
                                            )}
                                        </span>
                                        <em>
                                            {
                                                allOperatorsMapping[
                                                    (isPropertyFilterWithOperator(leafFilter) && leafFilter.operator) ||
                                                        'exact'
                                                ]
                                            }
                                        </em>{' '}
                                        {isAnyPropertyfilter(leafFilter) &&
                                            (Array.isArray(leafFilter.value) ? (
                                                leafFilter.value.map((subValue, index) => (
                                                    <React.Fragment key={index}>
                                                        <code className="SeriesDisplay__value">{subValue}</code>
                                                        {index <
                                                            (leafFilter.value as PropertyFilterBaseValue[]).length -
                                                                1 && ' or '}
                                                    </React.Fragment>
                                                ))
                                            ) : leafFilter.value != undefined ? (
                                                <code className="SeriesDisplay__value">{leafFilter.value}</code>
                                            ) : null)}
                                    </>
                                )}
                            </span>
                        </div>
                    </React.Fragment>
                )
            })}
        </>
    )
}

function DurationSummary({ filters }: { filters: RecordingUniversalFilters }): JSX.Element | null {
    if (!filters.duration || filters.duration.length === 0) {
        return null
    }

    return (
        <InsightDetailSectionDisplay icon={<IconClock />} label="Duration">
            {filters.duration.map((durationFilter, index) => (
                <React.Fragment key={index}>
                    <span className="font-medium">
                        {humanFriendlyDurationFilter(durationFilter, durationFilter.key as DurationType)}
                    </span>
                    {index < filters.duration.length - 1 && ' and '}
                </React.Fragment>
            ))}
        </InsightDetailSectionDisplay>
    )
}

function FiltersSummary({ filters }: { filters: RecordingUniversalFilters }): JSX.Element | null {
    const hasFilters = filters.filter_group && filters.filter_group.values.length > 0

    if (!hasFilters && !filters.filter_test_accounts) {
        return null
    }

    return (
        <InsightDetailSectionDisplay icon={<IconFilter />} label="Filters">
            <CompactUniversalFiltersDisplay groupFilter={filters.filter_group} />
            {filters.filter_test_accounts && (
                <div>
                    <LemonTag size="small">Test accounts excluded</LemonTag>
                </div>
            )}
        </InsightDetailSectionDisplay>
    )
}

function OrderingSummary({ filters }: { filters: RecordingUniversalFilters }): JSX.Element | null {
    if (!filters.order && !filters.order_direction) {
        return null
    }

    const orderLabels: Record<string, string> = {
        start_time: 'Start time',
        console_error_count: 'Console errors',
        click_count: 'Clicks',
        keypress_count: 'Key presses',
        mouse_activity_count: 'Mouse activity',
        activity_score: 'Activity score',
        recording_ttl: 'Recording TTL',
    }

    const orderLabel = filters.order ? orderLabels[filters.order] || filters.order : 'Start time'
    const direction = filters.order_direction === 'ASC' ? 'ascending' : 'descending'

    return (
        <InsightDetailSectionDisplay icon={<IconSort />} label="Sort order">
            <div className="font-medium">
                {orderLabel} ({direction})
            </div>
        </InsightDetailSectionDisplay>
    )
}

export function RecordingsUniversalFiltersDisplay({ filters }: { filters: RecordingUniversalFilters }): JSX.Element {
    return (
        <div className="px-3 py-2 space-y-2">
            <DateRangeSummary dateFrom={filters.date_from} dateTo={filters.date_to} />
            <DurationSummary filters={filters} />
            <FiltersSummary filters={filters} />
            <OrderingSummary filters={filters} />
        </div>
    )
}
