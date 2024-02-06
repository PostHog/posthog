import { useValues } from 'kea'
import {
    formatPropertyLabel,
    isAnyPropertyfilter,
    isCohortPropertyFilter,
    isPropertyFilterWithOperator,
} from 'lib/components/PropertyFilters/utils'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { IconCalculate, IconSubdirectoryArrowRight } from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { allOperatorsMapping, capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { LocalFilter, toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { BreakdownTag } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'
import { isPathsFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'
import { humanizePathsEventTypes } from 'scenes/insights/utils'
import { apiValueToMathType, MathCategory, MathDefinition, mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { filterForQuery, isInsightQueryNode } from '~/queries/utils'
import {
    FilterLogicalOperator,
    FilterType,
    InsightModel,
    InsightType,
    PathsFilterType,
    PropertyGroupFilter,
} from '~/types'

import { PropertyKeyInfo } from '../../PropertyKeyInfo'
import { TZLabel } from '../../TZLabel'

function CompactPropertyFiltersDisplay({
    groupFilter,
    embedded,
}: {
    groupFilter: PropertyGroupFilter | null
    embedded?: boolean
}): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const areAnyFiltersPresent = !!groupFilter && groupFilter.values.flatMap((subValues) => subValues.values).length > 0

    if (!areAnyFiltersPresent) {
        return <i>None</i>
    }

    return (
        <>
            {groupFilter.values.map(({ values: subValues, type: subType }, subIndex) => (
                <React.Fragment key={subIndex}>
                    {subIndex === 0 ? null : groupFilter.type === FilterLogicalOperator.Or ? 'OR' : 'AND'}
                    {subValues.map((leafFilter, leafIndex) => {
                        const isFirstFilterWithinSubgroup = leafIndex === 0
                        const isFirstFilterOverall = isFirstFilterWithinSubgroup && subIndex === 0

                        return (
                            <div key={leafIndex} className="SeriesDisplay__condition">
                                {embedded && <IconSubdirectoryArrowRight className="SeriesDisplay__arrow" />}
                                <span>
                                    {isFirstFilterWithinSubgroup
                                        ? embedded
                                            ? 'where '
                                            : null
                                        : subType === FilterLogicalOperator.Or
                                        ? 'or '
                                        : 'and '}
                                    {isCohortPropertyFilter(leafFilter) ? (
                                        <>
                                            {isFirstFilterOverall && !embedded ? 'Person' : 'person'} belongs to cohort
                                            <span className="SeriesDisplay__raw-name">
                                                {formatPropertyLabel(
                                                    leafFilter,
                                                    cohortsById,
                                                    (s) =>
                                                        formatPropertyValueForDisplay(leafFilter.key, s)?.toString() ||
                                                        '?'
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
                                                    <PropertyKeyInfo value={leafFilter.key} />
                                                )}
                                            </span>
                                            {
                                                allOperatorsMapping[
                                                    (isPropertyFilterWithOperator(leafFilter) && leafFilter.operator) ||
                                                        'exact'
                                                ]
                                            }{' '}
                                            <b>
                                                {isAnyPropertyfilter(leafFilter) &&
                                                    (Array.isArray(leafFilter.value)
                                                        ? leafFilter.value.join(' or ')
                                                        : leafFilter.value)}
                                            </b>
                                        </>
                                    )}
                                </span>
                            </div>
                        )
                    })}
                </React.Fragment>
            ))}
        </>
    )
}

function SeriesDisplay({
    filter,
    insightType = InsightType.TRENDS,
    index,
    hasBreakdown,
}: {
    filter: LocalFilter
    insightType?: InsightType
    index: number
    hasBreakdown: boolean
}): JSX.Element {
    const { mathDefinitions } = useValues(mathsLogic)

    const mathDefinition = mathDefinitions[
        insightType === InsightType.LIFECYCLE
            ? 'dau'
            : filter.math
            ? apiValueToMathType(filter.math, filter.math_group_type_index)
            : 'total'
    ] as MathDefinition | undefined

    return (
        <LemonRow
            fullWidth
            className="SeriesDisplay"
            icon={<SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />}
            extendedContent={
                <>
                    {insightType !== InsightType.FUNNELS && (
                        <div>
                            counted by{' '}
                            {mathDefinition?.category === MathCategory.HogQLExpression ? (
                                <code>{filter.math_hogql}</code>
                            ) : (
                                <>
                                    {mathDefinition?.category === MathCategory.PropertyValue &&
                                        filter.math_property && (
                                            <>
                                                {' '}
                                                event's
                                                <span className="SeriesDisplay__raw-name">
                                                    <PropertyKeyInfo value={filter.math_property} />
                                                </span>
                                            </>
                                        )}
                                    <b>{mathDefinition?.name.toLowerCase()}</b>
                                </>
                            )}
                        </div>
                    )}
                    {filter.properties && filter.properties.length > 0 && (
                        <CompactPropertyFiltersDisplay
                            groupFilter={{
                                type: FilterLogicalOperator.And,
                                values: [{ type: FilterLogicalOperator.And, values: filter.properties }],
                            }}
                            embedded
                        />
                    )}
                </>
            }
        >
            {insightType === InsightType.FUNNELS ? 'Performed' : 'Showing'}
            {filter.custom_name && <b> "{filter.custom_name}"</b>}
            {filter.type === 'actions' && filter.id ? (
                <Link
                    to={urls.action(filter.id)}
                    className="SeriesDisplay__raw-name SeriesDisplay__raw-name--action"
                    title="Action series"
                >
                    {filter.name}
                </Link>
            ) : (
                <span className="SeriesDisplay__raw-name SeriesDisplay__raw-name--event" title="Event series">
                    <PropertyKeyInfo value={filter.name || '$pageview'} />
                </span>
            )}
        </LemonRow>
    )
}

function PathsSummary({ filters }: { filters: Partial<PathsFilterType> }): JSX.Element {
    // Sync format with summarizePaths in utils
    return (
        <div className="SeriesDisplay">
            <div>
                User paths based on <b>{humanizePathsEventTypes(filters.include_event_types).join(' and ')}</b>
            </div>
            {filters.start_point && (
                <div>
                    starting at <b>{filters.start_point}</b>
                </div>
            )}
            {filters.end_point && (
                <div>
                    ending at <b>{filters.end_point}</b>
                </div>
            )}
        </div>
    )
}

export function QuerySummary({ filters }: { filters: Partial<FilterType> }): JSX.Element {
    const localFilters = toLocalFilters(filters)

    return (
        <>
            <h5>Query summary</h5>
            <section className="InsightDetails__query">
                {isTrendsFilter(filters) && filters.formula && (
                    <>
                        <LemonRow className="InsightDetails__formula" icon={<IconCalculate />} fullWidth>
                            <span>
                                Formula:<code>{filters.formula}</code>
                            </span>
                        </LemonRow>
                        <LemonDivider />
                    </>
                )}
                {isPathsFilter(filters) || localFilters.length > 0 ? (
                    <div className="InsightDetails__series">
                        {isPathsFilter(filters) ? (
                            <PathsSummary filters={filters} />
                        ) : (
                            <>
                                <SeriesDisplay
                                    hasBreakdown={!!filters.breakdown}
                                    filter={localFilters[0]}
                                    insightType={filters.insight}
                                    index={0}
                                />
                                {localFilters.slice(1).map((filter, index) => (
                                    <>
                                        <LemonDivider />
                                        <SeriesDisplay
                                            hasBreakdown={!!filters.breakdown}
                                            key={index}
                                            filter={filter}
                                            insightType={filters.insight}
                                            index={index + 1}
                                        />
                                    </>
                                ))}
                            </>
                        )}
                    </div>
                ) : (
                    /* TODO: Add support for Retention to InsightDetails */
                    <i>Unavailable for this insight type.</i>
                )}
            </section>
        </>
    )
}

export function FiltersSummary({ filters }: { filters: Partial<FilterType> }): JSX.Element {
    const groupFilter: PropertyGroupFilter | null = Array.isArray(filters.properties)
        ? {
              type: FilterLogicalOperator.And,
              values: [
                  {
                      type: FilterLogicalOperator.And,
                      values: filters.properties,
                  },
              ],
          }
        : filters.properties || null

    return (
        <>
            <h5>Filters</h5>
            <section>
                <CompactPropertyFiltersDisplay groupFilter={groupFilter} />
            </section>
        </>
    )
}

export function BreakdownSummary({ filters }: { filters: Partial<FilterType> }): JSX.Element | null {
    if (filters.breakdown_type == null || filters.breakdown == null) {
        return null
    }

    const breakdownArray = Array.isArray(filters.breakdown) ? filters.breakdown : [filters.breakdown]

    return (
        <>
            <h5>Breakdown by</h5>
            <section className="InsightDetails__breakdown">
                {breakdownArray.map((breakdown) => (
                    <BreakdownTag key={breakdown} breakdown={breakdown} breakdownType={filters.breakdown_type} />
                ))}
            </section>
        </>
    )
}

function InsightDetailsInternal({ insight }: { insight: InsightModel }, ref: React.Ref<HTMLDivElement>): JSX.Element {
    let { filters } = insight
    const { created_at, created_by } = insight
    if (!!insight.query && isInsightQueryNode(insight.query)) {
        filters = filterForQuery(insight.query) as Partial<FilterType>
    }
    return (
        <div className="InsightDetails" ref={ref}>
            <QuerySummary filters={filters} />
            <FiltersSummary filters={filters} />
            <BreakdownSummary filters={filters} />
            <div className="InsightDetails__footer">
                <div>
                    <h5>Created by</h5>
                    <section>
                        <ProfilePicture user={created_by} showName size="md" /> <TZLabel time={created_at} />
                    </section>
                </div>
                <div>
                    <h5>Last modified by</h5>
                    <section>
                        <ProfilePicture user={insight.last_modified_by} showName size="md" />{' '}
                        <TZLabel time={insight.last_modified_at} />
                    </section>
                </div>
            </div>
        </div>
    )
}
export const InsightDetails = React.memo(React.forwardRef(InsightDetailsInternal))
