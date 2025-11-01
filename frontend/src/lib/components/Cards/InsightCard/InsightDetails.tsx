import { useValues } from 'kea'
import React from 'react'

import { IconCalendar, IconCode2, IconFilter, IconGraph, IconPencil, IconSort, IconUser } from '@posthog/icons'
import { Lettermark, LettermarkColor } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { convertPropertiesToPropertyGroup } from 'lib/components/PropertyFilters/utils'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { IconCalculate } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, dateFilterToText } from 'lib/utils'
import { BreakdownTag } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'
import { humanizePathsEventTypes } from 'scenes/insights/utils'
import { MathCategory, MathDefinition, apiValueToMathType, mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'

import {
    AnyEntityNode,
    BreakdownFilter,
    FunnelsQuery,
    HogQLQuery,
    HogQLVariable,
    InsightQueryNode,
    LifecycleQuery,
    Node,
    NodeKind,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsFormulaNode,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    isActionsNode,
    isDataTableNodeWithHogQLQuery,
    isDataVisualizationNode,
    isEventsNode,
    isFunnelsQuery,
    isHogQLQuery,
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
import { CompactUniversalFiltersDisplay } from './RecordingsUniversalFiltersDisplay'

export function InsightDetailSectionDisplay({
    icon,
    label,
    children,
}: {
    icon: React.ReactNode
    label: string | JSX.Element
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex items-start gap-2 text-xs">
            <div className="flex text-muted-alt mt-px flex-shrink-0 text-sm">{icon}</div>
            <div className="flex-1 min-w-0">
                <div className="text-muted-alt mb-0.5">{label}</div>
                <div className="leading-6">{children}</div>
            </div>
        </section>
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
        <div className="SeriesDisplay">
            {isFunnelsQuery(query) ? (
                <Lettermark name={seriesIndex + 1} color={LettermarkColor.Gray} className="mt-px" />
            ) : (
                <SeriesLetter seriesIndex={seriesIndex} hasBreakdown={hasBreakdown} className="mt-0.5" />
            )}
            <div>
                {isFunnelsQuery(query) ? 'Performed' : 'Counting'}
                <EntityDisplay entity={series} />
                {!isFunnelsQuery(query) && (
                    <>
                        by{' '}
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
                    </>
                )}
                {series.properties && series.properties.length > 0 && (
                    <CompactUniversalFiltersDisplay
                        groupFilter={{
                            type: FilterLogicalOperator.And,
                            values: [{ type: FilterLogicalOperator.And, values: series.properties }],
                        }}
                        embedded
                    />
                )}
            </div>
        </div>
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
            <strong>and</strong> who came back to perform
            <EntityDisplay
                entity={
                    query.retentionFilter.returningEntity?.type === 'actions'
                        ? {
                              kind: NodeKind.ActionsNode,
                              name: query.retentionFilter.returningEntity.name,
                              id: query.retentionFilter.returningEntity.id as number,
                          }
                        : {
                              kind: NodeKind.EventsNode,
                              name: query.retentionFilter.returningEntity?.name,
                              event: query.retentionFilter.returningEntity?.id as string,
                          }
                }
            />
        </>
    )
}

export function SeriesSummary({
    query,
    heading,
}: {
    query: InsightQueryNode | HogQLQuery
    heading?: JSX.Element | null
}): JSX.Element {
    const Icon = isHogQLQuery(query) ? IconCode2 : IconGraph

    return (
        <InsightDetailSectionDisplay icon={<Icon />} label={heading !== null ? heading || 'Query' : ''}>
            {isHogQLQuery(query) ? (
                <CodeSnippet language={Language.SQL} maxLinesWithoutExpansion={8} compact>
                    {query.query}
                </CodeSnippet>
            ) : (
                <>
                    {isTrendsQuery(query) && <FormulaSummary query={query} />}
                    {isPathsQuery(query) ? (
                        <PathsSummary query={query} />
                    ) : isRetentionQuery(query) ? (
                        <RetentionSummary query={query} />
                    ) : isInsightQueryWithSeries(query) ? (
                        <>
                            {query.series.map((_entity, index) => (
                                <SeriesDisplay key={index} query={query} seriesIndex={index} />
                            ))}
                        </>
                    ) : (
                        <i>Query summary is not available for {(query as Node).kind} yet</i>
                    )}
                </>
            )}
        </InsightDetailSectionDisplay>
    )
}

export function FormulaSummary({ query }: { query: TrendsQuery }): JSX.Element | null {
    const formulaNodes =
        query.trendsFilter?.formulaNodes ||
        (query.trendsFilter?.formula ? ([{ formula: query.trendsFilter?.formula }] as TrendsFormulaNode[]) : null)

    if (formulaNodes == null) {
        return null
    }

    return (
        <>
            {formulaNodes.map((node) => (
                <div className="SeriesDisplay">
                    <IconCalculate className="text-xl m-px text-text-secondary-3000" />
                    <span>
                        Formula
                        {node.custom_name && (
                            <>
                                {' '}
                                <b>{node.custom_name}</b>
                            </>
                        )}
                        : <code>{node.formula}</code>
                    </span>
                </div>
            ))}
            <LemonDivider className="mt-1 mb-2" />
        </>
    )
}

export function PropertiesSummary({
    properties,
}: {
    properties: PropertyGroupFilter | AnyPropertyFilter[] | undefined | null
}): JSX.Element {
    return (
        <InsightDetailSectionDisplay icon={<IconFilter />} label="Filters">
            <CompactUniversalFiltersDisplay groupFilter={convertPropertiesToPropertyGroup(properties)} />
        </InsightDetailSectionDisplay>
    )
}

export function VariablesSummary({
    variables,
    variablesOverride,
}: {
    variables: Record<string, HogQLVariable> | undefined
    variablesOverride?: Record<string, HogQLVariable>
}): JSX.Element | null {
    if (!variables) {
        return null
    }

    return (
        <InsightDetailSectionDisplay icon={<IconCode2 />} label="Variables">
            {Object.entries(variables).map(([key, variable]) => {
                const overrideValue = variablesOverride?.[key]?.value
                const hasOverride = overrideValue !== undefined && overrideValue !== variable.value

                return (
                    <div key={key} className="flex items-center gap-2">
                        <span>
                            {variable.code_name}: {variable.value ? <strong>{variable.value}</strong> : <em>null</em>}
                        </span>
                        {hasOverride && (
                            <LemonTag type="highlight">
                                Overridden: {overrideValue ? <strong>{overrideValue}</strong> : <em>null</em>}
                            </LemonTag>
                        )}
                    </div>
                )
            })}
        </InsightDetailSectionDisplay>
    )
}

export function InsightBreakdownSummary({ query }: { query: InsightQueryNode | HogQLQuery }): JSX.Element | null {
    if (!isInsightQueryWithBreakdown(query) || !isValidBreakdown(query.breakdownFilter)) {
        return null
    }

    return <BreakdownSummary breakdownFilter={query.breakdownFilter} />
}

export function BreakdownSummary({
    breakdownFilter,
}: {
    breakdownFilter: BreakdownFilter | null | undefined
}): JSX.Element | null {
    if (!isValidBreakdown(breakdownFilter)) {
        return null
    }

    const content = Array.isArray(breakdownFilter.breakdowns) ? (
        <>
            {breakdownFilter.breakdowns.map((b) => (
                <BreakdownTag
                    key={`${b.type}-${b.property}`}
                    breakdown={b.property}
                    breakdownType={b.type}
                    size="small"
                />
            ))}
        </>
    ) : breakdownFilter.breakdown ? (
        <>
            {(Array.isArray(breakdownFilter.breakdown) ? breakdownFilter.breakdown : [breakdownFilter.breakdown]).map(
                (b) => (
                    <BreakdownTag key={b} breakdown={b} breakdownType={breakdownFilter.breakdown_type} size="small" />
                )
            )}
        </>
    ) : null

    if (!content) {
        return null
    }

    return (
        <InsightDetailSectionDisplay icon={<IconSort />} label="Breakdown by">
            {content}
        </InsightDetailSectionDisplay>
    )
}

export function DateRangeSummary({
    dateFrom,
    dateTo,
}: {
    dateFrom: string | null | undefined
    dateTo: string | null | undefined
}): JSX.Element | null {
    const dateFilterText = dateFilterToText(dateFrom, dateTo, null)
    if (!dateFilterText) {
        return null
    }
    return (
        <InsightDetailSectionDisplay icon={<IconCalendar />} label="Date range">
            <div className="font-medium">{dateFilterText}</div>
        </InsightDetailSectionDisplay>
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
    variablesOverride?: Record<string, HogQLVariable>
}

export const InsightDetails = React.memo(
    React.forwardRef<HTMLDivElement, InsightDetailsProps>(function InsightDetailsInternal(
        { query, footerInfo, variablesOverride },
        ref
    ): JSX.Element {
        return (
            <div className="InsightDetails space-y-2" ref={ref}>
                {(isInsightVizNode(query) ||
                    isDataVisualizationNode(query) ||
                    isDataTableNodeWithHogQLQuery(query)) && (
                    <>
                        <SeriesSummary query={query.source} />
                        <VariablesSummary
                            variables={isHogQLQuery(query.source) ? query.source.variables : undefined}
                            variablesOverride={variablesOverride}
                        />
                        <PropertiesSummary
                            properties={
                                isHogQLQuery(query.source) ? query.source.filters?.properties : query.source.properties
                            }
                        />
                        <InsightBreakdownSummary query={query.source} />
                    </>
                )}
                {footerInfo && (
                    <>
                        <InsightDetailSectionDisplay icon={<IconUser />} label="Created by">
                            <div className="flex items-center py-px gap-1.5">
                                <ProfilePicture user={footerInfo.created_by} showName size="sm" />
                                <TZLabel time={footerInfo.created_at} />
                            </div>
                        </InsightDetailSectionDisplay>
                        <InsightDetailSectionDisplay icon={<IconPencil />} label="Last modified by">
                            <div className="flex items-center py-px gap-1.5">
                                <ProfilePicture user={footerInfo.last_modified_by} showName size="sm" />
                                <TZLabel time={footerInfo.last_modified_at} />
                            </div>
                        </InsightDetailSectionDisplay>
                        {footerInfo.last_refresh && (
                            <InsightDetailSectionDisplay icon={<IconCalendar />} label="Last computed">
                                <TZLabel time={footerInfo.last_refresh} />
                            </InsightDetailSectionDisplay>
                        )}
                    </>
                )}
            </div>
        )
    })
)
