import './InsightDetails.scss'

import { useValues } from 'kea'
import React from 'react'

import {
    IconCalculator,
    IconCalendar,
    IconCode2,
    IconFilter,
    IconPencil,
    IconSort,
    IconUser,
    IconWarning,
} from '@posthog/icons'
import { Lettermark, LettermarkColor, Tooltip } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { convertPropertiesToPropertyGroup } from 'lib/components/PropertyFilters/utils'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
import { AnyPropertyFilter, BaseMathType, FilterLogicalOperator, PropertyGroupFilter, UserBasicType } from '~/types'

import { PropertyKeyInfo } from '../../PropertyKeyInfo'
import { TZLabel } from '../../TZLabel'
import { CompactUniversalFiltersDisplay } from './CompactUniversalFiltersDisplay'

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

type OverrideSource = 'dashboard' | 'tile'

interface EffectiveFilterOverrides {
    // Non-overlapping keys from both layers contribute; dashboard first to match backend order.
    propertyGroups: { properties: AnyPropertyFilter[]; source: OverrideSource }[]
    // Dashboard property filters the tile shadows on the same key — they don't apply, but we surface them
    // struck-through so the precedence is visible rather than silently dropped.
    overriddenByTile: AnyPropertyFilter[]
    // Breakdown is a single value: tile wins when set, otherwise the dashboard's.
    breakdown: { breakdownFilter: NonNullable<DashboardFilter['breakdown_filter']>; source: OverrideSource } | null
}

// NOTE: this re-derives the precedence encoded in the backend `merge_filters_by_priority` /
// `remove_query_properties_overridden_by` purely to attribute each shown filter to its source
// ("Dashboard"/"Tile"). It must stay in step with that backend rule — if the tie-break there changes
// (e.g. a field is added to `_SCALAR_OVERRIDE_FIELDS`), update this too or the tags will mislead.

// The (type, key) a property filter targets — the unit at which a tile takes precedence.
// Mirrors backend `_property_identity`.
function propertyIdentity(property: AnyPropertyFilter): string {
    const type = 'type' in property ? property.type : 'event'
    const key = 'key' in property ? property.key : ''
    return `${type}::${key}`
}

// Tile and dashboard overrides merge per field (matches backend `merge_filters_by_priority`).
// Property filters merge per key: a tile filter replaces the dashboard's on the same key.
// `mergeEnabled` mirrors the `DASHBOARD_TILE_FILTER_MERGE` flag gating the backend behavior — off, a
// tile override replaces the dashboard's wholesale (pre-merge behavior), matching what was computed.
export function getEffectiveFilterOverrides(
    filtersOverride: DashboardFilter | undefined,
    tileFiltersOverride: TileFilters | null | undefined,
    mergeEnabled: boolean
): EffectiveFilterOverrides {
    if (!mergeEnabled) {
        const override =
            tileFiltersOverride && Object.keys(tileFiltersOverride).length > 0
                ? { override: tileFiltersOverride, source: 'tile' as const }
                : filtersOverride && Object.keys(filtersOverride).length > 0
                  ? { override: filtersOverride, source: 'dashboard' as const }
                  : null
        return {
            propertyGroups:
                override && override.override.properties && override.override.properties.length > 0
                    ? [{ properties: override.override.properties, source: override.source }]
                    : [],
            overriddenByTile: [],
            breakdown: override?.override.breakdown_filter
                ? { breakdownFilter: override.override.breakdown_filter, source: override.source }
                : null,
        }
    }

    const tileProperties = tileFiltersOverride?.properties ?? []
    const tileKeys = new Set(tileProperties.map(propertyIdentity))
    const dashboardProperties: AnyPropertyFilter[] = []
    const overriddenByTile: AnyPropertyFilter[] = []
    for (const property of filtersOverride?.properties ?? []) {
        ;(tileKeys.has(propertyIdentity(property)) ? overriddenByTile : dashboardProperties).push(property)
    }
    const propertyGroups: EffectiveFilterOverrides['propertyGroups'] = []
    if (dashboardProperties.length > 0) {
        propertyGroups.push({ properties: dashboardProperties, source: 'dashboard' })
    }
    if (tileProperties.length > 0) {
        propertyGroups.push({ properties: tileProperties, source: 'tile' })
    }

    const breakdown = tileFiltersOverride?.breakdown_filter
        ? { breakdownFilter: tileFiltersOverride.breakdown_filter, source: 'tile' as const }
        : filtersOverride?.breakdown_filter
          ? { breakdownFilter: filtersOverride.breakdown_filter, source: 'dashboard' as const }
          : null

    return { propertyGroups, overriddenByTile, breakdown }
}

interface DateRangeSource {
    date_from?: string | null
    date_to?: string | null
}

interface EffectiveDateOverride {
    source: OverrideSource
    dateFrom: string | null | undefined
    dateTo: string | null | undefined
    // The lower-priority layer this replaced, shown struck-through so the precedence is visible.
    replaced?: {
        source: OverrideSource | 'insight'
        dateFrom: string | null | undefined
        dateTo: string | null | undefined
    }
}

function hasDateBound(source: DateRangeSource | null | undefined): boolean {
    // `!= null` (not truthiness) matches the backend's `is not None`, so an explicit empty-string bound counts.
    return source?.date_from != null || source?.date_to != null
}

// Works out which layer's date range actually applies and what it replaced, so the popup can show the
// tile/dashboard override with the overridden range struck-through. Mirrors the backend precedence in
// `merge_filters_by_priority` (tile beats dashboard beats the insight's own range); returns null when the
// insight's own range wins (nothing was overridden).
export function getDateRangeOverrideDisplay(
    insightDateRange: DateRangeSource | undefined,
    filtersOverride: DashboardFilter | undefined,
    tileFiltersOverride: TileFilters | null | undefined,
    mergeEnabled: boolean
): EffectiveDateOverride | null {
    const tileWins = mergeEnabled
        ? hasDateBound(tileFiltersOverride)
        : Object.keys(tileFiltersOverride ?? {}).length > 0
    const dashboardWins = mergeEnabled ? hasDateBound(filtersOverride) : Object.keys(filtersOverride ?? {}).length > 0

    let winner: {
        source: OverrideSource
        dateFrom: string | null | undefined
        dateTo: string | null | undefined
    } | null = null
    if (tileWins) {
        winner = { source: 'tile', dateFrom: tileFiltersOverride?.date_from, dateTo: tileFiltersOverride?.date_to }
    } else if (dashboardWins) {
        winner = { source: 'dashboard', dateFrom: filtersOverride?.date_from, dateTo: filtersOverride?.date_to }
    }
    if (!winner) {
        return null
    }

    let replaced: EffectiveDateOverride['replaced']
    if (winner.source === 'tile' && mergeEnabled && hasDateBound(filtersOverride)) {
        replaced = { source: 'dashboard', dateFrom: filtersOverride?.date_from, dateTo: filtersOverride?.date_to }
    } else if (hasDateBound(insightDateRange)) {
        replaced = { source: 'insight', dateFrom: insightDateRange?.date_from, dateTo: insightDateRange?.date_to }
    }
    if (replaced && replaced.dateFrom === winner.dateFrom && replaced.dateTo === winner.dateTo) {
        replaced = undefined
    }

    return { ...winner, replaced }
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

// Normalize a filter value into a canonical key for comparison. A scalar and its single-element array
// form mean the same filter (the insight editor and the dashboard bar store the same value differently),
// and the value list is a set — order and duplicates don't matter — so compare as a sorted set.
function normalizeFilterValue(value: unknown): string {
    const entries = value == null ? [] : Array.isArray(value) ? value : [value]
    return JSON.stringify([...new Set(entries.map((entry) => JSON.stringify(entry)))].sort())
}

// The override round-trips through the backend into the merged query and picks up normalized fields
// the raw override lacks, so a deep-equal fails — compare on the fields that actually identify a filter.
function isSamePropertyFilter(a: AnyPropertyFilter, b: AnyPropertyFilter): boolean {
    const operatorOf = (f: AnyPropertyFilter): string | undefined => ('operator' in f ? f.operator : undefined)
    return (
        (a.type ?? 'event') === (b.type ?? 'event') &&
        a.key === b.key &&
        (operatorOf(a) ?? 'exact') === (operatorOf(b) ?? 'exact') &&
        normalizeFilterValue(a.value) === normalizeFilterValue(b.value)
    )
}

function samePropertyFilters(a: AnyPropertyFilter[], b: AnyPropertyFilter[]): boolean {
    return a.length === b.length && a.every((f, i) => isSamePropertyFilter(f, b[i]))
}

// Matches the shape `convertPropertiesToPropertyGroup` accepts: a group, a flat list, or nothing.
type PropertiesInput = PropertyGroupFilter | AnyPropertyFilter[] | null | undefined

// Drop base leaves that are exact duplicates of a filter shown in a higher-priority override layer, so a
// filter the insight and an override both set isn't listed twice — it shows once, on the layer that took
// priority. Only exact matches (same type/key/operator/value) are collapsed; a shared key with a different
// value is left alone, since both genuinely AND together.
export function dropDuplicatesOfOverrides(
    base: PropertiesInput,
    overrideProperties: AnyPropertyFilter[]
): PropertiesInput {
    if (!base || overrideProperties.length === 0) {
        return base
    }
    const isDuplicate = (leaf: AnyPropertyFilter): boolean =>
        overrideProperties.some((override) => isSamePropertyFilter(leaf, override))
    if (Array.isArray(base)) {
        return base.filter((leaf) => !isDuplicate(leaf))
    }
    const values = (base.values ?? [])
        .map((subgroup) =>
            'values' in subgroup && Array.isArray(subgroup.values)
                ? { ...subgroup, values: (subgroup.values as AnyPropertyFilter[]).filter((leaf) => !isDuplicate(leaf)) }
                : subgroup
        )
        .filter((subgroup) => !('values' in subgroup && Array.isArray(subgroup.values) && subgroup.values.length === 0))
    return { ...base, values }
}

// The query returned for a dashboard tile already has the override's properties ANDed in (as the
// trailing subgroup/tail), so pull that part out to attribute it rather than list it twice.
function splitOutOverrideProperties(
    properties: PropertiesInput,
    overrideProperties: AnyPropertyFilter[]
): { base: PropertiesInput; overrideFound: boolean } {
    if (!properties || overrideProperties.length === 0) {
        return { base: properties, overrideFound: false }
    }
    // Flat list: the backend concatenated the override onto the end.
    if (Array.isArray(properties)) {
        const tailStart = properties.length - overrideProperties.length
        if (tailStart >= 0 && samePropertyFilters(properties.slice(tailStart), overrideProperties)) {
            return { base: properties.slice(0, tailStart), overrideFound: true }
        }
        return { base: properties, overrideFound: false }
    }
    // Group: the backend AND-wrapped the insight's group with the override as the final subgroup.
    const subgroups = properties.values ?? []
    const last = subgroups[subgroups.length - 1]
    if (last && samePropertyFilters(last.values as AnyPropertyFilter[], overrideProperties)) {
        return { base: { ...properties, values: subgroups.slice(0, -1) }, overrideFound: true }
    }
    return { base: properties, overrideFound: false }
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
    // A filter the insight and an override both set would otherwise show twice — collapse the base copy so
    // it appears once, on the layer that took priority.
    const dedupedBase = overrideFound ? dropDuplicatesOfOverrides(base, allOverrideProperties) : base
    // "Active filters" when overrides stack on top, so it's clear these are what actually applies vs the
    // replaced ones shown below; plain "Filters" otherwise.
    const label = overrideFound ? 'Active filters' : 'Filters'
    return (
        <InsightDetailSectionDisplay icon={<IconFilter />} label={label}>
            {/* Label the base as the insight's own only when overrides stack on top, so the layers read
                as a clear insight → dashboard → tile stack. Plain insights stay unlabeled. */}
            {overrideFound && <OverrideNote source="insight">base filters:</OverrideNote>}
            <CompactUniversalFiltersDisplay groupFilter={convertPropertiesToPropertyGroup(dedupedBase)} />
            {/* overrideFound means we removed the overrides from the list above, so show them once here. */}
            {overrideFound &&
                overrideGroups.map((group) => (
                    <React.Fragment key={group.source}>
                        <OverrideNote source={group.source}>filters added on top:</OverrideNote>
                        <CompactUniversalFiltersDisplay
                            groupFilter={convertPropertiesToPropertyGroup(group.properties)}
                        />
                    </React.Fragment>
                ))}
            {/* Dashboard filters the tile shadowed — labelled with the same layer badges as the applied
                rows ([Dashboard] replaced by [Tile]) and struck/dimmed so it reads as no longer applied. */}
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
    hasDataWarehouseSeries?: boolean
}

export const InsightDetails = React.memo(
    React.forwardRef<HTMLDivElement, InsightDetailsProps>(function InsightDetailsInternal(
        { query, footerInfo, variablesOverride, filtersOverride, tileFiltersOverride, hasDataWarehouseSeries },
        ref
    ): JSX.Element {
        const mergeEnabled = useFeatureFlag('DASHBOARD_TILE_FILTER_MERGE')
        const {
            propertyGroups,
            overriddenByTile,
            breakdown: overrideBreakdown,
        } = getEffectiveFilterOverrides(filtersOverride, tileFiltersOverride, mergeEnabled)
        const insightDateRange = isInsightVizNode(query) ? query.source.dateRange : undefined
        const dateOverride = getDateRangeOverrideDisplay(
            insightDateRange,
            filtersOverride,
            tileFiltersOverride,
            mergeEnabled
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
