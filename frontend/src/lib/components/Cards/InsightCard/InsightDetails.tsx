import './InsightDetails.scss'

import { useValues } from 'kea'
import React from 'react'

import {
    IconCalculator,
    IconCalendar,
    IconClock,
    IconCode2,
    IconFilter,
    IconPencil,
    IconPeople,
    IconSort,
    IconUser,
    IconWarning,
} from '@posthog/icons'
import { Lettermark, LettermarkColor, Tooltip } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { convertPropertiesToPropertyGroup } from 'lib/components/PropertyFilters/utils'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconCalculate } from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { BreakdownTag } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'
import { humanizePathsEventTypes, hasUnsupportedBreakdownForDataWarehouseTrends } from 'scenes/insights/utils'
import { QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { MathCategory, apiValueToMathType, mathsLogic } from 'scenes/trends/mathsLogic'
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
    AnyDataWarehouseNode,
    DashboardFilter,
    TileFilters,
} from '~/queries/schema/schema-general'
import {
    getInterval,
    isActionsNode,
    isAnyDataWarehouseNode,
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
    hasBreakdownFilter,
} from '~/queries/utils'
import {
    AnyPropertyFilter,
    BaseMathType,
    FilterLogicalOperator,
    InsightFilterOverrideContext,
    IntervalType,
    UserBasicType,
} from '~/types'

import { PropertyKeyInfo } from '../../PropertyKeyInfo'
import { TZLabel } from '../../TZLabel'
import { CompactUniversalFiltersDisplay } from './CompactUniversalFiltersDisplay'
import {
    dropDuplicatesOfOverrides,
    EffectiveDateOverride,
    getDateRangeOverrideDisplay,
    getEffectiveFilterOverrides,
    OverrideSource,
    PropertiesInput,
    splitOutOverrideProperties,
} from './insightDetailsFilterOverrides'

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

function assertNever(value: never): never {
    throw new Error(`Unexpected entity node: ${(value as { kind?: string } | undefined)?.kind ?? 'unknown'}`)
}

const LAYER_LABELS: Record<OverrideSource | 'insight', string> = {
    insight: 'Insight',
    dashboard: 'Dashboard',
    tile: 'Tile',
}

// Distinct colors per layer so the precedence stack reads at a glance: insight (base, grey) →
// dashboard (purple) → tile (accent, highest priority). Not primary/highlight for two of them — those
// share --color-accent and would look identical.
const LAYER_TAG_TYPE: Record<OverrideSource | 'insight', 'muted' | 'completion' | 'primary'> = {
    insight: 'muted',
    dashboard: 'completion',
    tile: 'primary',
}

function LayerTag({ source }: { source: OverrideSource | 'insight' }): JSX.Element {
    return (
        <LemonTag type={LAYER_TAG_TYPE[source]} size="small">
            {LAYER_LABELS[source]}
        </LemonTag>
    )
}

function OverrideNote({
    source,
    children,
}: {
    source: OverrideSource | 'insight'
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="mt-1.5 flex items-center gap-1">
            <LayerTag source={source} />
            <span className="text-muted-alt">{children}</span>
        </div>
    )
}

function EntityDisplay({ entity }: { entity: AnyEntityNode<AnyDataWarehouseNode> }): JSX.Element {
    let content: JSX.Element

    if (isActionsNode(entity)) {
        content = (
            <Link
                to={urls.action(entity.id)}
                className="SeriesDisplay__raw-name SeriesDisplay__raw-name--action"
                title="Action series"
            >
                {entity.name}
            </Link>
        )
    } else if (isEventsNode(entity)) {
        content = (
            <span className="SeriesDisplay__raw-name SeriesDisplay__raw-name--event" title="Event series">
                <PropertyKeyInfo value={entity.event || 'All events'} type={TaxonomicFilterGroupType.Events} />
            </span>
        )
    } else if (isAnyDataWarehouseNode(entity)) {
        content = (
            <span
                className="SeriesDisplay__raw-name SeriesDisplay__raw-name--data-warehouse"
                title="Data warehouse series"
            >
                <PropertyKeyInfo
                    value={entity.name || entity.table_name}
                    type={TaxonomicFilterGroupType.DataWarehouse}
                />
            </span>
        )
    } else {
        return assertNever(entity)
    }

    return (
        <>
            {entity.custom_name && <b> "{entity.custom_name}"</b>}
            {content}
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

    const hasBreakdown = isInsightQueryWithBreakdown(query) && hasBreakdownFilter(query.breakdownFilter)

    const mathKey = isLifecycleQuery(query)
        ? BaseMathType.UniqueUsers
        : series.math
          ? apiValueToMathType(series.math, series.math_group_type_index)
          : BaseMathType.TotalCount
    const mathDefinition = mathDefinitions[mathKey]

    const entityDisplay =
        series.kind === 'GroupNode' ? (
            series.nodes.map((node, i) => (
                <React.Fragment key={i}>
                    {i > 0 && <span className="text-muted"> or </span>}
                    <EntityDisplay entity={node} />
                </React.Fragment>
            ))
        ) : (
            <EntityDisplay entity={series} />
        )

    return (
        <div className="SeriesDisplay">
            {isFunnelsQuery(query) ? (
                <Lettermark name={seriesIndex + 1} color={LettermarkColor.Gray} className="mt-px" />
            ) : (
                <SeriesLetter seriesIndex={seriesIndex} hasBreakdown={hasBreakdown} className="mt-0.5" />
            )}
            <div>
                {isFunnelsQuery(query) ? 'Performed' : 'Counting'}
                {entityDisplay}
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
    const IconComponent = QUERY_TYPES_METADATA[query.kind].icon

    return (
        <InsightDetailSectionDisplay icon={<IconComponent />} label={heading !== null ? heading || 'Query' : ''}>
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
            {formulaNodes.map((node, index) => (
                <div className="SeriesDisplay" key={index}>
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
    overrides,
    overriddenByTile,
}: {
    properties: PropertiesInput
    overrides?: { properties: AnyPropertyFilter[]; source: OverrideSource }[] | null
    overriddenByTile?: AnyPropertyFilter[] | null
}): JSX.Element {
    const overrideGroups = overrides ?? []
    const overriddenProperties = overriddenByTile ?? []
    const allOverrideProperties = overrideGroups.flatMap((group) => group.properties)
    const { base, overrideFound } = splitOutOverrideProperties(properties, allOverrideProperties)
    const dedupedBase = overrideFound ? dropDuplicatesOfOverrides(base, allOverrideProperties) : base
    const label = overrideFound ? 'Active filters' : 'Filters'
    return (
        <InsightDetailSectionDisplay icon={<IconFilter />} label={label}>
            {overrideFound && <OverrideNote source="insight">base filters:</OverrideNote>}
            <CompactUniversalFiltersDisplay groupFilter={convertPropertiesToPropertyGroup(dedupedBase)} />
            {overrideFound &&
                overrideGroups.map((group) => (
                    <React.Fragment key={group.source}>
                        <OverrideNote source={group.source}>filters added on top:</OverrideNote>
                        <CompactUniversalFiltersDisplay
                            groupFilter={convertPropertiesToPropertyGroup(group.properties)}
                        />
                    </React.Fragment>
                ))}
            {/* Dashboard filters the tile shadowed — shown struck-through so precedence is visible. */}
            {overrideFound && overriddenProperties.length > 0 && (
                <>
                    <LemonDivider className="my-2" />
                    <div className="text-muted-alt">
                        <div className="mt-1.5 flex items-center gap-1">
                            <LayerTag source="dashboard" />
                            <span>filter replaced by</span>
                            <LayerTag source="tile" />
                        </div>
                        <div className="line-through opacity-60">
                            <CompactUniversalFiltersDisplay
                                groupFilter={convertPropertiesToPropertyGroup(overriddenProperties)}
                            />
                        </div>
                    </div>
                </>
            )}
        </InsightDetailSectionDisplay>
    )
}

export function PropertiesIgnoredWarning(): JSX.Element {
    return (
        <InsightDetailSectionDisplay icon={<IconFilter />} label="Filters">
            <Tooltip title="Filter overrides are not applied. Insights with a data warehouse series do not support filters.">
                <div className="flex items-center gap-1 text-warning italic">
                    <IconWarning /> Filter overrides ignored (data warehouse series).
                </div>
            </Tooltip>
        </InsightDetailSectionDisplay>
    )
}

export function BreakdownIgnoredWarning(): JSX.Element {
    return (
        <InsightDetailSectionDisplay icon={<IconSort />} label="Breakdown by">
            <Tooltip title="Breakdown overrides are not applied. Insights with a data warehouse series only support data warehouse property and HogQL breakdowns.">
                <div className="flex items-center gap-1 text-warning italic">
                    <IconWarning /> Breakdown overrides ignored (data warehouse series).
                </div>
            </Tooltip>
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
    if (!isInsightQueryWithBreakdown(query) || !hasBreakdownFilter(query.breakdownFilter)) {
        return null
    }

    return <BreakdownSummary breakdownFilter={query.breakdownFilter} />
}

export function BreakdownSummary({
    breakdownFilter,
    override,
}: {
    breakdownFilter: BreakdownFilter | null | undefined
    override?: { source: OverrideSource } | null
}): JSX.Element | null {
    if (!hasBreakdownFilter(breakdownFilter)) {
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
            {override && <OverrideNote source={override.source}>breakdown replaced with:</OverrideNote>}
            <div className="flex items-center gap-1 flex-wrap">{content}</div>
        </InsightDetailSectionDisplay>
    )
}

export function DateRangeSummary({
    dateFrom,
    dateTo,
    override,
}: {
    dateFrom: string | null | undefined
    dateTo: string | null | undefined
    override?: EffectiveDateOverride | null
}): JSX.Element | null {
    const dateFilterText = dateFilterToText(dateFrom, dateTo, null)
    if (!dateFilterText) {
        return null
    }
    const replaced = override?.replaced
    const replacedText = replaced ? dateFilterToText(replaced.dateFrom, replaced.dateTo, null) : null
    return (
        <InsightDetailSectionDisplay icon={<IconCalendar />} label="Date range">
            {/* Tag the value with its source layer rather than repeating "date range" in a note. */}
            <div className="flex items-center gap-1">
                <span className="font-medium">{dateFilterText}</span>
                {override && <LayerTag source={override.source} />}
            </div>
            {replaced && replacedText && (
                <div className="text-muted-alt text-xs mt-0.5 flex items-center gap-1">
                    <span>
                        was <span className="line-through">{replacedText}</span> from
                    </span>
                    <LayerTag source={replaced.source} />
                </div>
            )}
        </InsightDetailSectionDisplay>
    )
}

export function IntervalSummary({
    interval,
    override,
    insightInterval,
}: {
    interval: IntervalType
    override: { source: OverrideSource }
    insightInterval?: IntervalType | null
}): JSX.Element {
    const replaced = insightInterval != null && insightInterval !== interval ? insightInterval : null
    return (
        <InsightDetailSectionDisplay icon={<IconClock />} label="Grouped by">
            <div className="flex items-center gap-1">
                <span className="font-medium">{capitalizeFirstLetter(interval)}</span>
                <LayerTag source={override.source} />
            </div>
            {replaced && (
                <div className="text-muted-alt text-xs mt-0.5 flex items-center gap-1">
                    <span>
                        was <span className="line-through">{capitalizeFirstLetter(replaced)}</span> from
                    </span>
                    <LayerTag source="insight" />
                </div>
            )}
        </InsightDetailSectionDisplay>
    )
}

const testAccountsLabel = (excluded: boolean): string => (excluded ? 'Excluded' : 'Included')

export function TestAccountFilterSummary({
    filterTestAccounts,
    override,
    insightFilterTestAccounts,
}: {
    filterTestAccounts: boolean
    override: { source: OverrideSource }
    insightFilterTestAccounts?: boolean | null
}): JSX.Element {
    // Show what the insight itself had only when it explicitly set the toggle to the other state.
    const replaced =
        insightFilterTestAccounts != null && insightFilterTestAccounts !== filterTestAccounts
            ? insightFilterTestAccounts
            : null
    return (
        <InsightDetailSectionDisplay icon={<IconPeople />} label="Internal and test users">
            <div className="flex items-center gap-1">
                <span className="font-medium">{testAccountsLabel(filterTestAccounts)}</span>
                <LayerTag source={override.source} />
            </div>
            {replaced != null && (
                <div className="text-muted-alt text-xs mt-0.5 flex items-center gap-1">
                    <span>
                        was <span className="line-through">{testAccountsLabel(replaced)}</span> from
                    </span>
                    <LayerTag source="insight" />
                </div>
            )}
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
    filtersOverride?: DashboardFilter
    tileFiltersOverride?: TileFilters | null
    filterOverrideContext?: InsightFilterOverrideContext | null
    hasDataWarehouseSeries?: boolean
}

export const InsightDetails = React.memo(
    React.forwardRef<HTMLDivElement, InsightDetailsProps>(function InsightDetailsInternal(
        {
            query,
            footerInfo,
            variablesOverride,
            filtersOverride,
            tileFiltersOverride,
            filterOverrideContext,
            hasDataWarehouseSeries,
        },
        ref
    ): JSX.Element {
        const {
            propertyGroups,
            overriddenByTile,
            breakdown: overrideBreakdown,
            interval: overrideInterval,
            filterTestAccounts: overrideFilterTestAccounts,
        } = getEffectiveFilterOverrides(filterOverrideContext, filtersOverride, tileFiltersOverride)
        const insightDateRange = isInsightVizNode(query) ? query.source.dateRange : undefined
        const dateOverride = getDateRangeOverrideDisplay(
            insightDateRange,
            filterOverrideContext,
            filtersOverride,
            tileFiltersOverride
        )
        const overrideBreakdownFilter = overrideBreakdown?.breakdownFilter
        const hasPropertyOverrides = propertyGroups.length > 0
        const hasIgnoredBreakdownOverrides =
            isInsightVizNode(query) &&
            isTrendsQuery(query.source) &&
            hasUnsupportedBreakdownForDataWarehouseTrends(
                overrideBreakdownFilter ? { breakdown_filter: overrideBreakdownFilter } : null
            )

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
                        {dateOverride && (
                            <DateRangeSummary
                                dateFrom={dateOverride.dateFrom}
                                dateTo={dateOverride.dateTo}
                                override={dateOverride}
                            />
                        )}
                        {hasDataWarehouseSeries && hasPropertyOverrides ? (
                            <PropertiesIgnoredWarning />
                        ) : (
                            <PropertiesSummary
                                properties={
                                    isHogQLQuery(query.source)
                                        ? query.source.filters?.properties
                                        : query.source.properties
                                }
                                overrides={hasPropertyOverrides ? propertyGroups : null}
                                overriddenByTile={hasPropertyOverrides ? overriddenByTile : null}
                            />
                        )}
                        {hasDataWarehouseSeries && hasIgnoredBreakdownOverrides ? (
                            <BreakdownIgnoredWarning />
                        ) : overrideBreakdown && hasBreakdownFilter(overrideBreakdownFilter) ? (
                            <BreakdownSummary
                                breakdownFilter={overrideBreakdownFilter}
                                override={{ source: overrideBreakdown.source }}
                            />
                        ) : (
                            <InsightBreakdownSummary query={query.source} />
                        )}
                        {overrideInterval && (
                            <IntervalSummary
                                interval={overrideInterval.value}
                                override={{ source: overrideInterval.source }}
                                insightInterval={isInsightVizNode(query) ? getInterval(query.source) : null}
                            />
                        )}
                        {overrideFilterTestAccounts && (
                            <TestAccountFilterSummary
                                filterTestAccounts={overrideFilterTestAccounts.value}
                                override={{ source: overrideFilterTestAccounts.source }}
                                insightFilterTestAccounts={
                                    isHogQLQuery(query.source)
                                        ? query.source.filters?.filterTestAccounts
                                        : query.source.filterTestAccounts
                                }
                            />
                        )}
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
                            <InsightDetailSectionDisplay icon={<IconCalculator />} label="Last computed">
                                <TZLabel time={footerInfo.last_refresh} />
                            </InsightDetailSectionDisplay>
                        )}
                    </>
                )}
            </div>
        )
    })
)
