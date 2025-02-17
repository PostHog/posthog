import { useValues } from 'kea'
import {
    convertPropertiesToPropertyGroup,
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
    AnyEntityNode,
    FunnelsQuery,
    InsightQueryNode,
    LifecycleQuery,
    Node,
    NodeKind,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    isActionsNode,
    isEventsNode,
    isFunnelsQuery,
    isInsightQueryWithBreakdown,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isLifecycleQuery,
    isPathsQuery,
    isRetentionQuery,
    isTrendsQuery,
    isValidBreakdown,
} from '~/queries/utils'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyGroupFilter, UserBasicType } from '~/types'

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

function EntityDisplay({ entity }: { entity: AnyEntityNode }): JSX.Element {
    return (
        <>
            {entity.custom_name && <b> "{entity.custom_name}"</b>}
            {isActionsNode(entity) ? (
                <Link
                    to={urls.action(entity.id)}
                    className="SeriesDisplay__raw-name SeriesDisplay__raw-name--action"
                    title="Action series"
                >
                    {entity.name}
                </Link>
            ) : isEventsNode(entity) ? (
                <span className="SeriesDisplay__raw-name SeriesDisplay__raw-name--event" title="Event series">
                    <PropertyKeyInfo value={entity.event || '$pageview'} type={TaxonomicFilterGroupType.Events} />
                </span>
            ) : (
                <i>{entity.kind /* TODO: Support DataWarehouseNode */}</i>
            )}
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
    const series = query.series[seriesIndex]

    const hasBreakdown = isInsightQueryWithBreakdown(query) && isValidBreakdown(query.breakdownFilter)

    const mathDefinition = mathDefinitions[
        isLifecycleQuery(query)
            ? 'dau'
            : series.math
            ? apiValueToMathType(series.math, series.math_group_type_index)
            : 'total'
    ] as MathDefinition | undefined

    return (
        <LemonRow
            fullWidth
            className="SeriesDisplay"
            icon={<SeriesLetter seriesIndex={seriesIndex} hasBreakdown={hasBreakdown} />}
            extendedContent={
                series.properties &&
                series.properties.length > 0 && (
                    <CompactPropertyFiltersDisplay
                        groupFilter={{
                            type: FilterLogicalOperator.And,
                            values: [{ type: FilterLogicalOperator.And, values: series.properties }],
                        }}
                        embedded
                    />
                )
            }
        >
            <span>
                {isFunnelsQuery(query) ? 'Performed' : 'Showing'}
                <EntityDisplay entity={series} />
                {!isFunnelsQuery(query) && (
                    <span className="leading-none">
                        counted by{' '}
                        {mathDefinition?.category === MathCategory.HogQLExpression ? (
                            <code>{series.math_hogql}</code>
                        ) : (
                            <>
                                {mathDefinition?.category === MathCategory.PropertyValue && series.math_property && (
                                    <>
                                        {' '}
                                        event's
                                        <span className="SeriesDisplay__raw-name">
                                            <PropertyKeyInfo
                                                value={series.math_property}
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

function RetentionSummary({ query }: { query: RetentionQuery }): JSX.Element {
    const { aggregationLabel } = useValues(mathsLogic)

    return (
        <>
            {query.aggregation_group_type_index != null
                ? `${capitalizeFirstLetter(aggregationLabel(query.aggregation_group_type_index).plural)} which`
                : 'Users who'}
            {' performed'}
            <EntityDisplay
                entity={
                    query.retentionFilter.targetEntity?.type === 'actions'
                        ? {
                              kind: NodeKind.ActionsNode,
                              name: query.retentionFilter.targetEntity.name,
                              id: query.retentionFilter.targetEntity.id as number,
                          }
                        : {
                              kind: NodeKind.EventsNode,
                              name: query.retentionFilter.targetEntity?.name,
                              event: query.retentionFilter.targetEntity?.id as string,
                          }
                }
            />
            <strong>
                {query.retentionFilter.retentionType === 'retention_recurring' ? 'recurringly' : 'for the first time'}
            </strong>{' '}
            in the preceding{' '}
            <strong>
                {(query.retentionFilter.totalIntervals || 11) - 1}{' '}
                {query.retentionFilter.period?.toLocaleLowerCase() ?? 'day'}s
            </strong>
            <br />
            and came back to perform
            <EntityDisplay
                entity={
                    {
                        ...query.retentionFilter.returningEntity,
                        kind:
                            query.retentionFilter.returningEntity?.type === 'actions'
                                ? NodeKind.ActionsNode
                                : NodeKind.EventsNode,
                    } as AnyEntityNode
                }
            />
            in any of the next periods
        </>
    )
}

export function SeriesSummary({ query, heading }: { query: InsightQueryNode; heading?: JSX.Element }): JSX.Element {
    return (
        <section>
            <h5>{heading || 'Query summary'}</h5>
            <div className="InsightDetails__query">
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
                    ) : isRetentionQuery(query) ? (
                        <RetentionSummary query={query} />
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
                        <i>Query summary is not available for {(query as Node).kind} yet</i>
                    )}
                </div>
            </div>
        </section>
    )
}

export function PropertiesSummary({
    properties,
}: {
    properties: PropertyGroupFilter | AnyPropertyFilter[] | undefined
}): JSX.Element {
    return (
        <section>
            <h5>Filters</h5>
            <div>
                <CompactPropertyFiltersDisplay groupFilter={convertPropertiesToPropertyGroup(properties)} />
            </div>
        </section>
    )
}

export function BreakdownSummary({ query }: { query: InsightQueryNode }): JSX.Element | null {
    if (!isInsightQueryWithBreakdown(query) || !isValidBreakdown(query.breakdownFilter)) {
        return null
    }

    const { breakdown_type, breakdown, breakdowns } = query.breakdownFilter

    return (
        <section>
            <h5>Breakdown by</h5>
            <div>
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
            </div>
        </section>
    )
}

interface InsightDetailsProps {
    query: Node | null
    footerInfo?: {
        created_at: string
        created_by: UserBasicType | null
        last_modified_by: UserBasicType | null
        last_modified_at: string
        last_refresh: string | null
    }
}

export const InsightDetails = React.memo(
    React.forwardRef<HTMLDivElement, InsightDetailsProps>(function InsightDetailsInternal(
        { query, footerInfo },
        ref
    ): JSX.Element {
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
                {footerInfo && (
                    <div className="InsightDetails__footer">
                        <div>
                            <h5>Created by</h5>
                            <section>
                                <ProfilePicture user={footerInfo.created_by} showName size="md" />{' '}
                                <TZLabel time={footerInfo.created_at} />
                            </section>
                        </div>
                        <div>
                            <h5>Last modified by</h5>
                            <section>
                                <ProfilePicture user={footerInfo.last_modified_by} showName size="md" />{' '}
                                <TZLabel time={footerInfo.last_modified_at} />
                            </section>
                        </div>
                        {footerInfo.last_refresh && (
                            <div>
                                <h5>Last computed</h5>
                                <section>
                                    <TZLabel time={footerInfo.last_refresh} />
                                </section>
                            </div>
                        )}
                    </div>
                )}
            </div>
        )
    })
)
