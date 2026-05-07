import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { identifierToHuman } from 'lib/utils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { urls } from 'scenes/urls'

import { expandGroupNodes } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { nodeKindToInsightType } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { getDefaultQuery } from '~/queries/nodes/InsightViz/utils'
import {
    ActionsNode,
    AnyDataWarehouseNode,
    AnyEntityNode,
    BreakdownFilter,
    CalendarHeatmapFilter,
    DataTableNode,
    DataWarehouseNode,
    EntityNode,
    EventsNode,
    FunnelsDataWarehouseNode,
    FunnelsFilter,
    FunnelsQuery,
    GroupNode,
    InsightQueryNode,
    InsightVizNode,
    LifecycleDataWarehouseNode,
    LifecycleFilter,
    LifecycleQuery,
    NodeKind,
    PathsFilter,
    PathsQuery,
    ProductAnalyticsInsightQueryNode,
    RetentionFilter,
    RetentionQuery,
    StickinessFilter,
    StickinessQuery,
    TrendsFilter,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    containsHogQLQuery,
    getResultCustomizations,
    filterForQuery,
    isAnyDataWarehouseNode,
    isDataTableNode,
    isDataVisualizationNode,
    isDataWarehouseNode,
    isEndpointsUsageQuery,
    isEventsQuery,
    isFunnelsQuery,
    isFunnelsDataWarehouseNode,
    isHogQuery,
    isInsightQueryWithBreakdown,
    isInsightVizNode,
    isLifecycleDataWarehouseNode,
    isLifecycleQuery,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
    isWebAnalyticsInsightQuery,
} from '~/queries/utils'
import { BaseMathType, InsightLogicProps, InsightType, IntervalType } from '~/types'

import { PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS } from 'products/product_analytics/frontend/constants'

import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import type { insightNavLogicType } from './insightNavLogicType'

export interface Tab {
    label: string | JSX.Element
    type: InsightType
    dataAttr: string
}

type OmitConflictingProperties<T> = Omit<T, 'resultCustomizations'>

export interface CommonInsightFilter
    extends
        Partial<OmitConflictingProperties<TrendsFilter>>,
        Partial<OmitConflictingProperties<FunnelsFilter>>,
        Partial<RetentionFilter>,
        Partial<PathsFilter>,
        Partial<StickinessFilter>,
        Partial<LifecycleFilter> {}

export interface QueryPropertyCache
    extends
        Omit<Partial<TrendsQuery>, 'kind' | 'response' | 'series'>,
        Omit<Partial<FunnelsQuery>, 'kind' | 'response' | 'series'>,
        Omit<Partial<RetentionQuery>, 'kind' | 'response' | 'series'>,
        Omit<Partial<PathsQuery>, 'kind' | 'response'>,
        Omit<Partial<StickinessQuery>, 'kind' | 'response' | 'series'>,
        Omit<Partial<LifecycleQuery>, 'kind' | 'response' | 'series'> {
    series?: (AnyEntityNode<AnyDataWarehouseNode> | GroupNode)[]
    commonFilter: CommonInsightFilter
    commonFilterTrendsStickiness?: {
        resultCustomizations?: Record<string, any>
    }
    trendsFilter?: Partial<TrendsQuery['trendsFilter']>
    calendarHeatmapFilter?: Partial<CalendarHeatmapFilter>
}

const cleanSeriesEntityMath = (
    entity: AnyEntityNode<AnyDataWarehouseNode> | GroupNode,
    mathAvailability: MathAvailability
): AnyEntityNode<AnyDataWarehouseNode> | GroupNode => {
    const { math, math_property, math_group_type_index, math_hogql, ...baseEntity } = entity

    // Recursively clean nested nodes in GroupNode
    if ('nodes' in baseEntity && Array.isArray(baseEntity.nodes)) {
        baseEntity.nodes = baseEntity.nodes.map(
            (node) => cleanSeriesEntityMath(node, mathAvailability) as AnyEntityNode
        )
    }

    if (mathAvailability === MathAvailability.All) {
        if (math != null) {
            return { ...baseEntity, math, math_property, math_group_type_index, math_hogql }
        }
        return { ...baseEntity, math: BaseMathType.TotalCount }
    } else if (mathAvailability === MathAvailability.ActorsOnly) {
        if (math != null) {
            return { ...baseEntity, math, math_property, math_group_type_index, math_hogql }
        }
        return { ...baseEntity, math: BaseMathType.UniqueUsers }
    }
    return baseEntity
}

const cleanSeriesMath = (
    series: (AnyEntityNode<AnyDataWarehouseNode> | GroupNode)[],
    mathAvailability: MathAvailability
): (AnyEntityNode<AnyDataWarehouseNode> | GroupNode)[] => {
    return series.map((entity) => cleanSeriesEntityMath(entity, mathAvailability))
}

type DataWarehouseNodeKind =
    | NodeKind.DataWarehouseNode
    | NodeKind.FunnelsDataWarehouseNode
    | NodeKind.LifecycleDataWarehouseNode

type DataWarehouseNodeSharedFields = Partial<{
    id_field: DataWarehouseNode['id_field']
    distinct_id_field: DataWarehouseNode['distinct_id_field']
    aggregation_target_field: FunnelsDataWarehouseNode['aggregation_target_field']
    created_at_field: LifecycleDataWarehouseNode['created_at_field']
}>

const cleanDataWarehouseNode = (
    entity: AnyEntityNode<AnyDataWarehouseNode> | GroupNode,
    dataWarehouseNodeKind: DataWarehouseNodeKind
): AnyEntityNode<AnyDataWarehouseNode> | GroupNode => {
    if ('nodes' in entity && Array.isArray(entity.nodes)) {
        return {
            ...entity,
            nodes: entity.nodes.map((node) => cleanDataWarehouseNode(node, dataWarehouseNodeKind) as AnyEntityNode),
        }
    }

    if (!isAnyDataWarehouseNode(entity) || entity.kind === dataWarehouseNodeKind) {
        return entity
    }

    const {
        kind: _kind,
        id_field,
        distinct_id_field,
        aggregation_target_field,
        created_at_field,
        ...baseEntity
    } = entity as EntityNode & DataWarehouseNodeSharedFields

    if (dataWarehouseNodeKind === NodeKind.DataWarehouseNode) {
        return {
            ...baseEntity,
            kind: NodeKind.DataWarehouseNode,
            ...(id_field ? { id_field } : {}),
            distinct_id_field:
                distinct_id_field ??
                (isFunnelsDataWarehouseNode(entity) || isLifecycleDataWarehouseNode(entity)
                    ? entity.aggregation_target_field
                    : undefined),
        } as AnyEntityNode | GroupNode
    }

    if (dataWarehouseNodeKind === NodeKind.FunnelsDataWarehouseNode) {
        return {
            ...baseEntity,
            kind: NodeKind.FunnelsDataWarehouseNode,
            ...(id_field ? { id_field } : {}),
            aggregation_target_field:
                aggregation_target_field ?? (isDataWarehouseNode(entity) ? entity.distinct_id_field : undefined),
        } as FunnelsDataWarehouseNode | GroupNode
    }

    return {
        ...baseEntity,
        kind: NodeKind.LifecycleDataWarehouseNode,
        aggregation_target_field:
            aggregation_target_field ?? (isDataWarehouseNode(entity) ? entity.distinct_id_field : undefined),
        created_at_field: created_at_field ?? entity.timestamp_field,
    } as LifecycleDataWarehouseNode | GroupNode
}

const cleanDataWarehouseNodes = (
    series: (AnyEntityNode<AnyDataWarehouseNode> | GroupNode)[],
    dataWarehouseNodeKind: DataWarehouseNodeKind
): (AnyEntityNode<AnyDataWarehouseNode> | GroupNode)[] => {
    return series.map((entity) => cleanDataWarehouseNode(entity, dataWarehouseNodeKind))
}

const cleanSeries = (
    series: (AnyEntityNode<AnyDataWarehouseNode> | GroupNode)[],
    mathAvailability: MathAvailability,
    dataWarehouseNodeKind: DataWarehouseNodeKind
): (AnyEntityNode<AnyDataWarehouseNode> | GroupNode)[] => {
    return cleanSeriesMath(cleanDataWarehouseNodes(series, dataWarehouseNodeKind), mathAvailability)
}

// --- Field capability map ---
// Defines which "transferable" fields each insight type supports and how to
// adapt cached values when merging into a new query type. Both
// cachePropertiesFromQuery and mergeCachedProperties derive behavior from this.
//
// Field present = supported. Function = transform before applying. `true` = pass through.

type SeriesArray = (AnyEntityNode<AnyDataWarehouseNode> | GroupNode)[]

interface InsightTypeCapabilities {
    series?: ((series: SeriesArray) => SeriesArray) | true
    seriesMath?: true
    interval?: ((interval: IntervalType) => IntervalType) | true
    breakdownFilter?: ((bf: BreakdownFilter) => BreakdownFilter) | true
    compareFilter?: true
    funnelPathsFilter?: true
    aggregationGroupTypeIndex?: true
}

const downgradeMinuteInterval = (interval: IntervalType): IntervalType => (interval === 'minute' ? 'hour' : interval)

const truncateToSingleBreakdown = (bf: BreakdownFilter): BreakdownFilter => {
    if (bf.breakdowns?.length) {
        const first = bf.breakdowns[0]
        return {
            ...bf,
            breakdowns: undefined,
            breakdown: first.property,
            breakdown_type: first.type,
            breakdown_histogram_bin_count: first.histogram_bin_count,
            breakdown_group_type_index: first.group_type_index,
            breakdown_normalize_url: first.normalize_url,
        }
    }
    return { ...bf, breakdowns: undefined }
}

const filterRetentionBreakdowns = (bf: BreakdownFilter): BreakdownFilter => {
    if (!bf.breakdowns) {
        return bf
    }
    return { ...bf, breakdowns: bf.breakdowns.filter((b) => b.type === 'person' || b.type === 'event') }
}

const carryForwardSeriesMath = (newSeries: SeriesArray, cachedSeries: SeriesArray | undefined): SeriesArray => {
    if (!cachedSeries) {
        return newSeries
    }
    return newSeries.map((entity, index) => {
        const cachedEntity = cachedSeries[index]
        if (cachedEntity && cachedEntity.math !== undefined && entity.math === undefined) {
            return {
                ...entity,
                math: cachedEntity.math,
                ...(cachedEntity.math_property != null ? { math_property: cachedEntity.math_property } : {}),
                ...(cachedEntity.math_group_type_index != null
                    ? { math_group_type_index: cachedEntity.math_group_type_index }
                    : {}),
                ...(cachedEntity.math_hogql != null ? { math_hogql: cachedEntity.math_hogql } : {}),
            }
        }
        return entity
    })
}

const FIELD_CAPABILITIES: Partial<Record<NodeKind, InsightTypeCapabilities>> = {
    [NodeKind.TrendsQuery]: {
        series: (s) => cleanSeries(s, MathAvailability.All, NodeKind.DataWarehouseNode),
        seriesMath: true,
        interval: true,
        breakdownFilter: true,
        compareFilter: true,
        aggregationGroupTypeIndex: true,
    },
    [NodeKind.FunnelsQuery]: {
        series: (s) => cleanSeries(s, MathAvailability.FunnelsOnly, NodeKind.FunnelsDataWarehouseNode),
        interval: downgradeMinuteInterval,
        breakdownFilter: truncateToSingleBreakdown,
        aggregationGroupTypeIndex: true,
    },
    [NodeKind.RetentionQuery]: {
        // TODO: map series to/from retentionFilter.targetEntity/returningEntity so switching
        // between Retention and other insight types preserves configured events.
        breakdownFilter: filterRetentionBreakdowns,
    },
    [NodeKind.PathsQuery]: {
        funnelPathsFilter: true,
    },
    [NodeKind.StickinessQuery]: {
        series: (s) =>
            cleanSeries(
                expandGroupNodes(s as (EventsNode | ActionsNode | DataWarehouseNode | GroupNode)[]),
                MathAvailability.ActorsOnly,
                NodeKind.DataWarehouseNode
            ),
        seriesMath: true,
        interval: downgradeMinuteInterval,
        compareFilter: true,
    },
    [NodeKind.LifecycleQuery]: {
        series: (s) =>
            cleanSeries(
                expandGroupNodes(s as (EventsNode | ActionsNode | DataWarehouseNode | GroupNode)[]).slice(0, 1),
                MathAvailability.None,
                NodeKind.LifecycleDataWarehouseNode
            ),
        interval: downgradeMinuteInterval,
    },
}

type TrendsCommonVisualizationProperties = Pick<TrendsFilter, 'showValuesOnSeries' | 'showPercentStackView' | 'display'>
type StickinessCommonVisualizationProperties = Pick<StickinessFilter, 'showValuesOnSeries' | 'display'>
type FunnelsCommonVisualizationProperties = Pick<FunnelsFilter, 'showValuesOnSeries'>
type LifecycleCommonVisualizationProperties = Pick<LifecycleFilter, 'showValuesOnSeries'>
type EmptyCommonVisualizationProperties = Record<never, never>

function getCommonVisualizationProperties(
    query: TrendsQuery,
    commonFilter: CommonInsightFilter
): Partial<TrendsCommonVisualizationProperties>
function getCommonVisualizationProperties(
    query: StickinessQuery,
    commonFilter: CommonInsightFilter
): Partial<StickinessCommonVisualizationProperties>
function getCommonVisualizationProperties(
    query: FunnelsQuery,
    commonFilter: CommonInsightFilter
): Partial<FunnelsCommonVisualizationProperties>
function getCommonVisualizationProperties(
    query: LifecycleQuery,
    commonFilter: CommonInsightFilter
): Partial<LifecycleCommonVisualizationProperties>
function getCommonVisualizationProperties(
    query: RetentionQuery,
    commonFilter: CommonInsightFilter
): Partial<EmptyCommonVisualizationProperties>
function getCommonVisualizationProperties(
    query: PathsQuery,
    commonFilter: CommonInsightFilter
): Partial<EmptyCommonVisualizationProperties>
function getCommonVisualizationProperties(
    query: InsightQueryNode,
    commonFilter: CommonInsightFilter
):
    | Partial<TrendsCommonVisualizationProperties>
    | Partial<StickinessCommonVisualizationProperties>
    | Partial<FunnelsCommonVisualizationProperties>
    | Partial<LifecycleCommonVisualizationProperties>
    | Partial<EmptyCommonVisualizationProperties> {
    const sharedProperties = {
        ...((isLifecycleQuery(query) || isStickinessQuery(query) || isTrendsQuery(query) || isFunnelsQuery(query)) &&
        commonFilter.showValuesOnSeries
            ? { showValuesOnSeries: commonFilter.showValuesOnSeries }
            : {}),
        ...(isTrendsQuery(query) && commonFilter.showPercentStackView
            ? { showPercentStackView: commonFilter.showPercentStackView }
            : {}),
        ...((isTrendsQuery(query) || isStickinessQuery(query)) && commonFilter.display
            ? { display: commonFilter.display }
            : {}),
    }

    if (isTrendsQuery(query)) {
        return sharedProperties as Partial<TrendsCommonVisualizationProperties>
    }
    if (isStickinessQuery(query)) {
        return sharedProperties as Partial<StickinessCommonVisualizationProperties>
    }
    if (isFunnelsQuery(query)) {
        return sharedProperties as Partial<FunnelsCommonVisualizationProperties>
    }
    if (isLifecycleQuery(query)) {
        return sharedProperties as Partial<LifecycleCommonVisualizationProperties>
    }
    return {} as Partial<EmptyCommonVisualizationProperties>
}

export const insightNavLogic = kea<insightNavLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'InsightNav', 'insightNavLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            insightDataLogic(props),
            ['query'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
        ],
        actions: [insightDataLogic(props), ['setQuery']],
    })),
    actions({
        setActiveView: (view: InsightType) => ({ view }),
        updateQueryPropertyCache: (cache: QueryPropertyCache) => ({ cache }),
    }),
    reducers({
        queryPropertyCache: [
            null as QueryPropertyCache | null,
            {
                updateQueryPropertyCache: (state, { cache }) => ({
                    ...state,
                    ...cache,
                }),
            },
        ],
    }),
    selectors({
        activeView: [
            (s) => [s.query],
            (query) => {
                if (isDataTableNode(query)) {
                    return InsightType.JSON
                } else if (containsHogQLQuery(query)) {
                    return InsightType.SQL
                } else if (isHogQuery(query)) {
                    return InsightType.HOG
                } else if (isInsightVizNode(query)) {
                    // Check for Web Analytics queries first before using the mapping
                    if (isWebAnalyticsInsightQuery(query.source)) {
                        return InsightType.WEB_ANALYTICS
                    }
                    return nodeKindToInsightType[query.source.kind] || InsightType.TRENDS
                }
                return InsightType.JSON
            },
        ],
        tabs: [
            (s) => [s.activeView, s.query, s.featureFlags],
            (activeView, query, featureFlags) => {
                const tabs: Tab[] = [
                    {
                        label: 'Trends',
                        type: InsightType.TRENDS,
                        dataAttr: 'insight-trends-tab',
                    },
                    {
                        label: 'Funnels',
                        type: InsightType.FUNNELS,
                        dataAttr: 'insight-funnels-tab',
                    },
                    {
                        label: 'Retention',
                        type: InsightType.RETENTION,
                        dataAttr: 'insight-retention-tab',
                    },
                    {
                        label: 'User Paths',
                        type: InsightType.PATHS,
                        dataAttr: 'insight-path-tab',
                    },
                    {
                        label: 'Stickiness',
                        type: InsightType.STICKINESS,
                        dataAttr: 'insight-stickiness-tab',
                    },
                    {
                        label: 'Lifecycle',
                        type: InsightType.LIFECYCLE,
                        dataAttr: 'insight-lifecycle-tab',
                    },
                ]

                if (featureFlags[FEATURE_FLAGS.HOG] || activeView === InsightType.HOG) {
                    tabs.push({
                        label: <>Hog 🦔</>,
                        type: InsightType.HOG,
                        dataAttr: 'insight-hog-tab',
                    })
                }

                if (activeView === InsightType.WEB_ANALYTICS) {
                    // Like the json only, this is a temporary tab for Web Analytics insights.
                    // We don't display it otherwise and humans shouldn't be able to click to select this tab
                    // it only opens when you select "Open as new insight" from the Web Analytics dashboard.
                    tabs.push({
                        label: (
                            <>
                                Web Analytics{' '}
                                <LemonTag type="warning" className="uppercase ml-2">
                                    Beta
                                </LemonTag>
                            </>
                        ),
                        type: InsightType.WEB_ANALYTICS,
                        dataAttr: 'insight-web-analytics-tab',
                    })
                }

                if (activeView === InsightType.JSON && !isEndpointsUsageQuery(query)) {
                    // only display this tab when it is selected by the provided insight query
                    // don't display it otherwise... humans shouldn't be able to click to select this tab
                    // it only opens when you click the <OpenEditorButton/>
                    // EndpointsUsage queries should not appear in the insight editor at all
                    const humanFriendlyQueryKind: string | null =
                        typeof query?.kind === 'string'
                            ? identifierToHuman(query.kind.replace(/(Node|Query)$/g, ''), 'title')
                            : null
                    tabs.push({
                        label: (
                            <>
                                {humanFriendlyQueryKind ?? 'Custom'}{' '}
                                <LemonTag type="warning" className="uppercase ml-2">
                                    Beta
                                </LemonTag>
                            </>
                        ),
                        type: InsightType.JSON,
                        dataAttr: 'insight-json-tab',
                    })
                }

                return tabs
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        setActiveView: ({ view }) => {
            const query = getDefaultQuery(view, values.filterTestAccountsDefault)

            if (isDataVisualizationNode(query)) {
                router.actions.push(urls.sqlEditor({ query: query.source.query }))
            } else if (isInsightVizNode(query)) {
                const source = values.queryPropertyCache
                    ? mergeCachedProperties(query.source, values.queryPropertyCache)
                    : query.source
                actions.setQuery({
                    ...query,
                    source: { ...source, tags: { ...source.tags, ...PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS } },
                } as InsightVizNode)
            } else {
                actions.setQuery(query)
            }
        },
        setQuery: ({ query }) => {
            if (isInsightVizNode(query)) {
                actions.updateQueryPropertyCache(cachePropertiesFromQuery(query.source, values.queryPropertyCache))
            } else if (isDataTableNode(query)) {
                const seeded = cachePropertiesFromDataTable(query)
                if (seeded) {
                    actions.updateQueryPropertyCache(seeded)
                }
            }
        },
    })),
    afterMount(({ values, actions }) => {
        if (values.query && isInsightVizNode(values.query)) {
            actions.updateQueryPropertyCache(cachePropertiesFromQuery(values.query.source, values.queryPropertyCache))
        } else if (values.query && isDataTableNode(values.query)) {
            const seeded = cachePropertiesFromDataTable(values.query)
            if (seeded) {
                actions.updateQueryPropertyCache(seeded)
            }
        }
    }),
])

const cachePropertiesFromDataTable = (query: DataTableNode): QueryPropertyCache | null => {
    if (!isEventsQuery(query.source)) {
        return null
    }
    const source = query.source
    const cache: Partial<QueryPropertyCache> = {}

    if (source.properties?.length) {
        cache.properties = JSON.parse(JSON.stringify(source.properties))
    }
    if (source.after || source.before) {
        cache.dateRange = {
            ...(source.after ? { date_from: source.after } : {}),
            ...(source.before ? { date_to: source.before } : {}),
        }
    }

    const seriesEvents = source.events?.length ? source.events : source.event ? [source.event] : []
    if (seriesEvents.length) {
        cache.series = seriesEvents.map((event) => ({
            kind: NodeKind.EventsNode,
            event,
            name: event,
        }))
    }

    return Object.keys(cache).length > 0 ? (cache as QueryPropertyCache) : null
}

const cachePropertiesFromQuery = (query: InsightQueryNode, cache: QueryPropertyCache | null): QueryPropertyCache => {
    const newCache = JSON.parse(JSON.stringify(query)) as QueryPropertyCache

    if (isWebAnalyticsInsightQuery(query)) {
        return newCache
    }

    // Preserve explicit removals for global filters when merging with the existing cache.
    newCache.properties = query.properties === undefined ? undefined : JSON.parse(JSON.stringify(query.properties))

    // Preserve cached values that the current query type doesn't fully support,
    // so they survive a round-trip when switching back.
    const caps = FIELD_CAPABILITIES[query.kind]
    if (cache?.series && !caps?.series) {
        newCache.series = cache.series
    }
    if (cache?.interval && !caps?.interval) {
        newCache.interval = cache.interval
    }
    if (cache?.breakdownFilter && !caps?.breakdownFilter) {
        newCache.breakdownFilter = cache.breakdownFilter
    }
    if (cache?.compareFilter && !caps?.compareFilter) {
        newCache.compareFilter = cache.compareFilter
    }
    if (cache?.funnelPathsFilter && !caps?.funnelPathsFilter) {
        newCache.funnelPathsFilter = cache.funnelPathsFilter
    }
    if (cache?.aggregation_group_type_index !== undefined && !caps?.aggregationGroupTypeIndex) {
        newCache.aggregation_group_type_index = cache.aggregation_group_type_index
    }
    // Only Trends supports multiple breakdowns — preserve the full set through
    // types that truncate to single breakdown (Funnels, Retention)
    if (cache?.breakdownFilter?.breakdowns?.length && !isTrendsQuery(query) && isInsightQueryWithBreakdown(query)) {
        newCache.breakdownFilter = cache.breakdownFilter
    }
    // Preserve minute interval through types that downgrade it to hour
    if (cache?.interval === 'minute' && !isTrendsQuery(query)) {
        newCache.interval = cache.interval
    }
    if (caps?.series && !caps?.seriesMath && cache?.series && newCache.series) {
        newCache.series = carryForwardSeriesMath(newCache.series, cache.series)
    }

    /** store the insight specific filter in commonFilter */
    const insightFilter = filterForQuery(query)
    const resultCustomizations = getResultCustomizations(query)
    // exclude properties that shouldn't be shared
    let commonProperties = insightFilter || {}
    if (isTrendsQuery(query)) {
        const { resultCustomizations: _resultCustomizations, ...trendsCommonProperties } = query.trendsFilter || {}
        commonProperties = trendsCommonProperties
    } else if (isStickinessQuery(query)) {
        const { resultCustomizations: _resultCustomizations, ...stickinessCommonProperties } =
            query.stickinessFilter || {}
        commonProperties = stickinessCommonProperties
    } else if (isFunnelsQuery(query)) {
        const { resultCustomizations: _resultCustomizations, ...funnelsCommonProperties } = query.funnelsFilter || {}
        commonProperties = funnelsCommonProperties
    }
    newCache.commonFilter = { ...cache?.commonFilter, ...commonProperties }

    /** store the insight specific filter for trend and stickiness queries */
    if (isTrendsQuery(query) || isStickinessQuery(query)) {
        newCache.commonFilterTrendsStickiness = {
            ...cache?.commonFilterTrendsStickiness,
            ...(resultCustomizations !== undefined ? { resultCustomizations } : {}),
        }
    }

    return newCache
}

const mergeCachedProperties = (query: InsightQueryNode, cache: QueryPropertyCache): InsightQueryNode => {
    if (isWebAnalyticsInsightQuery(query)) {
        return query
    }

    const mergedQuery = {
        ...query,
        ...(cache.dateRange ? { dateRange: cache.dateRange } : {}),
        ...(cache.properties !== undefined ? { properties: cache.properties } : {}),
        ...(cache.samplingFactor ? { samplingFactor: cache.samplingFactor } : {}),
    }

    // Insight-specific filter merge (web analytics already returned above)
    return {
        ...mergedQuery,
        ...buildCachedFields(query, cache),
        ...buildInsightFilter(query, cache),
    } as InsightQueryNode
}

const buildCachedFields = (query: InsightQueryNode, cache: QueryPropertyCache): Partial<QueryPropertyCache> => {
    const caps = FIELD_CAPABILITIES[query.kind]
    if (!caps) {
        return {}
    }

    const result: Partial<QueryPropertyCache> = {}
    if (caps.series && cache.series) {
        result.series = (
            typeof caps.series === 'function' ? caps.series(cache.series) : cache.series
        ) as QueryPropertyCache['series']
    }
    if (caps.interval && cache.interval) {
        result.interval = typeof caps.interval === 'function' ? caps.interval(cache.interval) : cache.interval
    }
    if (caps.breakdownFilter && cache.breakdownFilter) {
        result.breakdownFilter =
            typeof caps.breakdownFilter === 'function'
                ? caps.breakdownFilter(cache.breakdownFilter)
                : cache.breakdownFilter
    }
    if (caps.compareFilter && cache.compareFilter) {
        result.compareFilter = cache.compareFilter
    }
    if (caps.funnelPathsFilter && cache.funnelPathsFilter) {
        result.funnelPathsFilter = cache.funnelPathsFilter
    }
    if (caps.aggregationGroupTypeIndex && cache.aggregation_group_type_index !== undefined) {
        result.aggregation_group_type_index = cache.aggregation_group_type_index
    }
    return result
}

const buildInsightFilter = (
    query: InsightQueryNode,
    cache: QueryPropertyCache
): Partial<ProductAnalyticsInsightQueryNode> => {
    if (!cache.commonFilter) {
        return {}
    }

    const trendsStickinessResultCustomizations = cache.commonFilterTrendsStickiness?.resultCustomizations
        ? { resultCustomizations: cache.commonFilterTrendsStickiness.resultCustomizations }
        : {}

    if (isTrendsQuery(query)) {
        const vizProps = getCommonVisualizationProperties(query, cache.commonFilter)
        return {
            trendsFilter: {
                ...query.trendsFilter,
                ...cache.trendsFilter,
                ...vizProps,
                ...trendsStickinessResultCustomizations,
            },
        }
    }
    if (isStickinessQuery(query)) {
        const vizProps = getCommonVisualizationProperties(query, cache.commonFilter)
        return {
            stickinessFilter: {
                ...query.stickinessFilter,
                ...cache.stickinessFilter,
                ...vizProps,
                ...trendsStickinessResultCustomizations,
            },
        }
    }
    if (isFunnelsQuery(query)) {
        const vizProps = getCommonVisualizationProperties(query, cache.commonFilter)
        return { funnelsFilter: { ...query.funnelsFilter, ...cache.funnelsFilter, ...vizProps } }
    }
    if (isRetentionQuery(query)) {
        const vizProps = getCommonVisualizationProperties(query, cache.commonFilter)
        return { retentionFilter: { ...query.retentionFilter, ...cache.retentionFilter, ...vizProps } }
    }
    if (isPathsQuery(query)) {
        const vizProps = getCommonVisualizationProperties(query, cache.commonFilter)
        return { pathsFilter: { ...query.pathsFilter, ...cache.pathsFilter, ...vizProps } }
    }
    if (isLifecycleQuery(query)) {
        const vizProps = getCommonVisualizationProperties(query, cache.commonFilter)
        return { lifecycleFilter: { ...query.lifecycleFilter, ...cache.lifecycleFilter, ...vizProps } }
    }
    return {}
}
