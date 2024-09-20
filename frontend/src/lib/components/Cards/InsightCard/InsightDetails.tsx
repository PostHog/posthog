import { useValues } from 'kea'
import {
    formatPropertyLabel,
    isAnyPropertyfilter,
    isCohortPropertyFilter,
    isPropertyFilterWithOperator,
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
} from 'lib/components/PropertyFilters/utils'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconCalculate } from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { allOperatorsMapping, capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { BreakdownTag } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'
import { humanizePathsEventTypes } from 'scenes/insights/utils'
import { apiValueToMathType, MathCategory, MathDefinition, mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    FunnelsQuery,
    InsightQueryNode,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema'
import {
    isFunnelsQuery,
    isInsightQueryWithBreakdown,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isLifecycleQuery,
    isPathsQuery,
    isTrendsQuery,
    isValidBreakdown,
} from '~/queries/utils'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    FilterType,
    PropertyGroupFilter,
    QueryBasedInsightModel,
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
                    {subIndex === 0 ? null : (
                        <em className="text-[11px] font-semibold">
                            {groupFilter.type === FilterLogicalOperator.Or ? 'OR' : 'AND'}
                        </em>
                    )}
                    {subValues.map((leafFilter, leafIndex) => {
                        const isFirstFilterWithinSubgroup = leafIndex === 0
                        const isFirstFilterOverall = isFirstFilterWithinSubgroup && subIndex === 0

                        return (
                            <div key={leafIndex} className="SeriesDisplay__condition">
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
    query,
    seriesIndex,
}: {
    query: TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery
    seriesIndex: number
}): JSX.Element {
    const { mathDefinitions } = useValues(mathsLogic)
    const filter = query.series[seriesIndex]

    const hasBreakdown = isInsightQueryWithBreakdown(query) && isValidBreakdown(query.breakdownFilter)

    const mathDefinition = mathDefinitions[
        isLifecycleQuery(query)
            ? 'dau'
            : filter.math
            ? apiValueToMathType(filter.math, filter.math_group_type_index)
            : 'total'
    ] as MathDefinition | undefined

    return (
        <LemonRow
            fullWidth
            className="SeriesDisplay"
            icon={<SeriesLetter seriesIndex={seriesIndex} hasBreakdown={hasBreakdown} />}
            extendedContent={
                filter.properties &&
                filter.properties.length > 0 && (
                    <CompactPropertyFiltersDisplay
                        groupFilter={{
                            type: FilterLogicalOperator.And,
                            values: [{ type: FilterLogicalOperator.And, values: filter.properties }],
                        }}
                        embedded
                    />
                )
            }
        >
            <span>
                {isFunnelsQuery(query) ? 'Performed' : 'Showing'}
                {filter.custom_name && <b> "{filter.custom_name}"</b>}
                {filter.kind === NodeKind.ActionsNode && filter.id ? (
                    <Link
                        to={urls.action(filter.id)}
                        className="SeriesDisplay__raw-name SeriesDisplay__raw-name--action"
                        title="Action series"
                    >
                        {filter.name}
                    </Link>
                ) : (
                    <span className="SeriesDisplay__raw-name SeriesDisplay__raw-name--event" title="Event series">
                        <PropertyKeyInfo value={filter.name || '$pageview'} type={TaxonomicFilterGroupType.Events} />
                    </span>
                )}
                {!isFunnelsQuery(query) && (
                    <span className="leading-none">
                        counted by{' '}
                        {mathDefinition?.category === MathCategory.HogQLExpression ? (
                            <code>{filter.math_hogql}</code>
                        ) : (
                            <>
                                {mathDefinition?.category === MathCategory.PropertyValue && filter.math_property && (
                                    <>
                                        {' '}
                                        event's
                                        <span className="SeriesDisplay__raw-name">
                                            <PropertyKeyInfo
                                                value={filter.math_property}
                                                type={TaxonomicFilterGroupType.EventProperties}
                                            />
                                        </span>
                                    </>
                                )}
                                <b>{mathDefinition?.name.toLowerCase()}</b>
                            </>
                        )}
                    </span>
                )}
            </span>
        </LemonRow>
    )
}

function PathsSummary({ query }: { query: PathsQuery }): JSX.Element {
    // Sync format with summarizePaths in utils
    const { includeEventTypes, startPoint, endPoint } = query.pathsFilter
    return (
        <div className="SeriesDisplay">
            <div>
                User paths based on <b>{humanizePathsEventTypes(includeEventTypes).join(' and ')}</b>
            </div>
            {startPoint && (
                <div>
                    starting at <b>{startPoint}</b>
                </div>
            )}
            {endPoint && (
                <div>
                    ending at <b>{endPoint}</b>
                </div>
            )}
        </div>
    )
}

export function SeriesSummary({ query }: { query: InsightQueryNode }): JSX.Element {
    return (
        <>
            <h5>Query summary</h5>
            <section className="InsightDetails__query">
                {isTrendsQuery(query) && query.trendsFilter?.formula && (
                    <>
                        <LemonRow className="InsightDetails__formula" icon={<IconCalculate />} fullWidth>
                            <span>
                                Formula:<code>{query.trendsFilter?.formula}</code>
                            </span>
                        </LemonRow>
                        <LemonDivider />
                    </>
                )}
                <div className="InsightDetails__series">
                    {isPathsQuery(query) ? (
                        <PathsSummary query={query} />
                    ) : isInsightQueryWithSeries(query) ? (
                        <>
                            {query.series.map((_entity, index) => (
                                <React.Fragment key={index}>
                                    {index !== 0 && <LemonDivider className="my-1" />}
                                    <SeriesDisplay query={query} seriesIndex={index} />
                                </React.Fragment>
                            ))}
                        </>
                    ) : (
                        /* TODO: Add support for Retention to InsightDetails */
                        <i>Unavailable for this insight type.</i>
                    )}
                </div>
            </section>
        </>
    )
}

export function PropertiesSummary({
    properties,
}: {
    properties: PropertyGroupFilter | AnyPropertyFilter[] | undefined
}): JSX.Element {
    const groupFilter: PropertyGroupFilter | null = Array.isArray(properties)
        ? {
              type: FilterLogicalOperator.And,
              values: [
                  {
                      type: FilterLogicalOperator.And,
                      values: properties,
                  },
              ],
          }
        : properties || null

    return (
        <>
            <h5>Filters</h5>
            <section>
                <CompactPropertyFiltersDisplay groupFilter={groupFilter} />
            </section>
        </>
    )
}

export function LEGACY_FilterBasedBreakdownSummary({ filters }: { filters: Partial<FilterType> }): JSX.Element | null {
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

export function BreakdownSummary({ query }: { query: InsightQueryNode }): JSX.Element | null {
    if (!isInsightQueryWithBreakdown(query) || !isValidBreakdown(query.breakdownFilter)) {
        return null
    }

    const { breakdown_type, breakdown, breakdowns } = query.breakdownFilter

    return (
        <>
            <h5>Breakdown by</h5>
            <section className="InsightDetails__breakdown">
                {Array.isArray(breakdowns)
                    ? breakdowns.map((b) => (
                          <BreakdownTag key={`${b.type}-${b.property}`} breakdown={b.property} breakdownType={b.type} />
                      ))
                    : breakdown &&
                      (Array.isArray(breakdown)
                          ? breakdown
                          : [breakdown].map((b) => (
                                <BreakdownTag key={b} breakdown={b} breakdownType={breakdown_type} />
                            )))}
            </section>
        </>
    )
}

function InsightDetailsInternal(
    { insight }: { insight: QueryBasedInsightModel },
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { created_at, created_by, query } = insight

    // TODO: Implement summaries for HogQL query insights
    return (
        <div className="InsightDetails" ref={ref}>
            {isInsightVizNode(query) && (
                <>
                    <SeriesSummary query={query.source} />
                    <PropertiesSummary properties={query.source.properties} />
                    <BreakdownSummary query={query.source} />
                </>
            )}
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
                {insight.last_refresh && (
                    <div>
                        <h5>Last computed</h5>
                        <section>
                            <TZLabel time={insight.last_refresh} />
                        </section>
                    </div>
                )}
            </div>
        </div>
    )
}
export const InsightDetails = React.memo(React.forwardRef(InsightDetailsInternal))
