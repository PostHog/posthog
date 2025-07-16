import { IconExternal } from '@posthog/icons'
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

import { nodeKindToInsightType } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { getDefaultQuery } from '~/queries/nodes/InsightViz/utils'
import {
    ActionsNode,
    DataWarehouseNode,
    EventsNode,
    FunnelsFilter,
    FunnelsQuery,
    InsightQueryNode,
    InsightVizNode,
    LifecycleFilter,
    LifecycleQuery,
    PathsFilter,
    PathsQuery,
    RetentionFilter,
    RetentionQuery,
    StickinessFilter,
    StickinessQuery,
    TrendsFilter,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    containsHogQLQuery,
    filterKeyForQuery,
    getDisplay,
    getShowPercentStackView,
    getShowValuesOnSeries,
    isDataTableNode,
    isDataVisualizationNode,
    isFunnelsQuery,
    isHogQuery,
    isInsightQueryWithBreakdown,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isLifecycleQuery,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { BaseMathType, InsightLogicProps, InsightType } from '~/types'

import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import type { insightNavLogicType } from './insightNavLogicType'

export interface Tab {
    label: string | JSX.Element
    type: InsightType
    dataAttr: string
}

type OmitConflictingProperties<T> = Omit<T, 'resultCustomizations'>

export interface CommonInsightFilter
    extends Partial<OmitConflictingProperties<TrendsFilter>>,
        Partial<OmitConflictingProperties<FunnelsFilter>>,
        Partial<RetentionFilter>,
        Partial<PathsFilter>,
        Partial<StickinessFilter>,
        Partial<LifecycleFilter> {}

export interface QueryPropertyCache
    extends Omit<Partial<TrendsQuery>, 'kind' | 'response'>,
        Omit<Partial<FunnelsQuery>, 'kind' | 'response'>,
        Omit<Partial<RetentionQuery>, 'kind' | 'response'>,
        Omit<Partial<PathsQuery>, 'kind' | 'response'>,
        Omit<Partial<StickinessQuery>, 'kind' | 'response'>,
        Omit<Partial<LifecycleQuery>, 'kind' | 'response'> {
    commonFilter: CommonInsightFilter
}

const cleanSeriesEntityMath = (
    entity: EventsNode | ActionsNode | DataWarehouseNode,
    mathAvailability: MathAvailability
): EventsNode | ActionsNode | DataWarehouseNode => {
    const { math, math_property, math_group_type_index, math_hogql, ...baseEntity } = entity

    // TODO: This should be improved to keep a math that differs from the default.
    // For this we need to know wether the math was actively changed e.g.
    // On which insight type the math properties have been set.
    if (mathAvailability === MathAvailability.All) {
        // return entity with default all availability math set
        return { ...baseEntity, math: BaseMathType.TotalCount }
    } else if (mathAvailability === MathAvailability.ActorsOnly) {
        // return entity with default actors only availability math set
        return { ...baseEntity, math: BaseMathType.UniqueUsers }
    }
    // return entity without math properties for insights that don't support it
    return baseEntity
}

const cleanSeriesMath = (
    series: (EventsNode | ActionsNode | DataWarehouseNode)[],
    mathAvailability: MathAvailability
): (EventsNode | ActionsNode | DataWarehouseNode)[] => {
    return series.map((entity) => cleanSeriesEntityMath(entity, mathAvailability))
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
                    {
                        label: (
                            <>
                                SQL <IconExternal />
                            </>
                        ),
                        type: InsightType.SQL,
                        dataAttr: 'insight-sql-tab',
                    },
                    ...(featureFlags[FEATURE_FLAGS.CALENDAR_HEATMAP_INSIGHT]
                        ? [
                              {
                                  label: (
                                      <>
                                          Calendar heatmap
                                          <LemonTag type="warning" className="uppercase ml-2">
                                              Beta
                                          </LemonTag>
                                      </>
                                  ),
                                  type: InsightType.CALENDAR_HEATMAP,
                                  dataAttr: 'insight-calendar-heatmap-tab',
                              },
                          ]
                        : []),
                ]

                if (featureFlags[FEATURE_FLAGS.HOG] || activeView === InsightType.HOG) {
                    tabs.push({
                        label: <>Hog 🦔</>,
                        type: InsightType.HOG,
                        dataAttr: 'insight-hog-tab',
                    })
                }

                if (activeView === InsightType.JSON) {
                    // only display this tab when it is selected by the provided insight query
                    // don't display it otherwise... humans shouldn't be able to click to select this tab
                    // it only opens when you click the <OpenEditorButton/>
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
                router.actions.push(urls.sqlEditor(query.source.query))
            } else if (isInsightVizNode(query)) {
                actions.setQuery({
                    ...query,
                    source: values.queryPropertyCache
                        ? mergeCachedProperties(query.source, values.queryPropertyCache)
                        : query.source,
                } as InsightVizNode)
            } else {
                actions.setQuery(query)
            }
        },
        setQuery: ({ query }) => {
            if (isInsightVizNode(query)) {
                actions.updateQueryPropertyCache(cachePropertiesFromQuery(query.source, values.queryPropertyCache))
            }
        },
    })),
    afterMount(({ values, actions }) => {
        if (values.query && isInsightVizNode(values.query)) {
            actions.updateQueryPropertyCache(cachePropertiesFromQuery(values.query.source, values.queryPropertyCache))
        }
    }),
])

const cachePropertiesFromQuery = (query: InsightQueryNode, cache: QueryPropertyCache | null): QueryPropertyCache => {
    const newCache = JSON.parse(JSON.stringify(query)) as QueryPropertyCache

    // // set series (first two entries) from retention target and returning entity
    // if (isRetentionQuery(query)) {
    //     const { targetEntity, returningEntity } = query.retentionFilter || {}
    //     const series = actionsAndEventsToSeries({
    //         events: [
    //             ...(targetEntity?.type === 'events' ? [targetEntity as ActionFilter] : []),
    //             ...(returningEntity?.type === 'events' ? [returningEntity as ActionFilter] : []),
    //         ],
    //         actions: [
    //             ...(targetEntity?.type === 'actions' ? [targetEntity as ActionFilter] : []),
    //             ...(returningEntity?.type === 'actions' ? [returningEntity as ActionFilter] : []),
    //         ],
    //     })
    //     if (series.length > 0) {
    //         newCache.series = [...series, ...(cache?.series ? cache.series.slice(series.length) : [])]
    //     }
    // }

    if (isLifecycleQuery(query)) {
        newCache.series = cache?.series
    }

    /**  store the insight specific filter in commonFilter */
    const filterKey = filterKeyForQuery(query)
    // exclude properties that shouldn't be shared
    const { resultCustomizations, ...commonProperties } = query[filterKey] || {}
    newCache.commonFilter = { ...cache?.commonFilter, ...commonProperties }

    return newCache
}

const mergeCachedProperties = (query: InsightQueryNode, cache: QueryPropertyCache): InsightQueryNode => {
    const mergedQuery = {
        ...query,
        ...(cache.dateRange ? { dateRange: cache.dateRange } : {}),
        ...(cache.properties ? { properties: cache.properties } : {}),
        ...(cache.samplingFactor ? { samplingFactor: cache.samplingFactor } : {}),
    }

    // series
    if (isInsightQueryWithSeries(mergedQuery)) {
        if (cache.series) {
            if (isLifecycleQuery(mergedQuery)) {
                mergedQuery.series = cleanSeriesMath(cache.series.slice(0, 1), MathAvailability.None)
            } else {
                const mathAvailability = isTrendsQuery(mergedQuery)
                    ? MathAvailability.All
                    : isStickinessQuery(mergedQuery)
                    ? MathAvailability.ActorsOnly
                    : MathAvailability.None
                mergedQuery.series = cleanSeriesMath(cache.series, mathAvailability)
            }
        }
        // else if (cache.retentionFilter?.targetEntity || cache.retentionFilter?.returningEntity) {
        //     mergedQuery.series = [
        //         ...(cache.retentionFilter.targetEntity
        //             ? [cache.retentionFilter.targetEntity as EventsNode | ActionsNode]
        //             : []),
        //         ...(cache.retentionFilter.returningEntity
        //             ? [cache.retentionFilter.returningEntity as EventsNode | ActionsNode]
        //             : []),
        //     ]
        // }
    } else if (isRetentionQuery(mergedQuery) && cache.series) {
        // mergedQuery.retentionFilter = {
        //     ...mergedQuery.retentionFilter,
        //     ...(cache.series.length > 0 ? { targetEntity: cache.series[0] } : {}),
        //     ...(cache.series.length > 1 ? { returningEntity: cache.series[1] } : {}),
        // }
    }

    // interval
    if (isInsightQueryWithSeries(mergedQuery) && cache.interval) {
        // Only support real time queries on trends for now
        if (!isTrendsQuery(mergedQuery) && cache.interval == 'minute') {
            mergedQuery.interval = 'hour'
        } else {
            mergedQuery.interval = cache.interval
        }
    }

    // breakdown filter
    if (isInsightQueryWithBreakdown(mergedQuery) && cache.breakdownFilter) {
        mergedQuery.breakdownFilter = cache.breakdownFilter

        // If we've changed the query kind, convert multiple breakdowns to a single breakdown
        if (isTrendsQuery(cache) && isFunnelsQuery(query)) {
            if (cache.breakdownFilter.breakdowns?.length) {
                const firstBreakdown = cache.breakdownFilter?.breakdowns?.[0]
                mergedQuery.breakdownFilter = {
                    ...cache.breakdownFilter,
                    breakdowns: undefined,
                    breakdown: firstBreakdown?.property,
                    breakdown_type: firstBreakdown?.type,
                    breakdown_histogram_bin_count: firstBreakdown?.histogram_bin_count,
                    breakdown_group_type_index: firstBreakdown?.group_type_index,
                    breakdown_normalize_url: firstBreakdown?.normalize_url,
                }
            } else {
                mergedQuery.breakdownFilter = {
                    ...cache.breakdownFilter,
                    breakdowns: undefined,
                }
            }
        }

        if (isRetentionQuery(query) && cache.breakdownFilter?.breakdowns) {
            mergedQuery.breakdownFilter = {
                ...query.breakdownFilter,
                breakdowns: cache.breakdownFilter.breakdowns.filter((b) => b.type === 'person' || b.type === 'event'),
            }
        }
    }

    // funnel paths filter
    if (isPathsQuery(mergedQuery) && cache.funnelPathsFilter) {
        mergedQuery.funnelPathsFilter = cache.funnelPathsFilter
    }

    // insight specific filter
    const filterKey = filterKeyForQuery(mergedQuery)
    if (cache[filterKey] || cache.commonFilter) {
        const node = { kind: mergedQuery.kind, [filterKey]: cache.commonFilter } as unknown as InsightQueryNode
        mergedQuery[filterKey] = {
            ...query[filterKey],
            ...cache[filterKey],
            // TODO: fix an issue where switching between trends and funnels with the option enabled would
            // result in an error before uncommenting
            // ...(getCompare(node) ? { compare: getCompare(node) } : {}),
            ...(getShowValuesOnSeries(node) ? { showValuesOnSeries: getShowValuesOnSeries(node) } : {}),
            ...(getShowPercentStackView(node) ? { showPercentStackView: getShowPercentStackView(node) } : {}),
            ...(getDisplay(node) ? { display: getDisplay(node) } : {}),
        }
    }

    return mergedQuery
}
