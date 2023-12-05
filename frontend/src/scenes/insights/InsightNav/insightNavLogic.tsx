import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic, queryFromKind } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'

import { examples, TotalEventsTable } from '~/queries/examples'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { insightMap } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { getDisplay, getShowPercentStackView, getShowValueOnSeries } from '~/queries/nodes/InsightViz/utils'
import {
    ActionsNode,
    EventsNode,
    FunnelsFilter,
    FunnelsQuery,
    InsightQueryNode,
    InsightVizNode,
    LifecycleFilter,
    LifecycleQuery,
    NodeKind,
    PathsFilter,
    PathsQuery,
    RetentionFilter,
    RetentionQuery,
    StickinessFilter,
    StickinessQuery,
    TrendsFilter,
    TrendsQuery,
} from '~/queries/schema'
import {
    containsHogQLQuery,
    filterKeyForQuery,
    isInsightQueryWithBreakdown,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isRetentionQuery,
} from '~/queries/utils'
import { ActionFilter, InsightLogicProps, InsightType } from '~/types'

import type { insightNavLogicType } from './insightNavLogicType'

export interface Tab {
    label: string | JSX.Element
    type: InsightType
    dataAttr: string
}

export interface CommonInsightFilter
    extends Partial<TrendsFilter>,
        Partial<FunnelsFilter>,
        Partial<RetentionFilter>,
        Partial<PathsFilter>,
        Partial<StickinessFilter>,
        Partial<LifecycleFilter> {}

export interface QueryPropertyCache
    extends Omit<Partial<TrendsQuery>, 'kind' | 'response'>,
        Omit<Partial<FunnelsQuery>, 'kind'>,
        Omit<Partial<RetentionQuery>, 'kind' | 'response'>,
        Omit<Partial<PathsQuery>, 'kind'>,
        Omit<Partial<StickinessQuery>, 'kind'>,
        Omit<Partial<LifecycleQuery>, 'kind'> {
    commonFilter: CommonInsightFilter
}

export const insightNavLogic = kea<insightNavLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'InsightNav', 'insightNavLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['filters'],
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
        userSelectedView: [
            null as InsightType | null,
            {
                setActiveView: (_, { view }) => view,
            },
        ],
    }),
    selectors({
        activeView: [
            (s) => [s.filters, s.query, s.userSelectedView],
            (filters, query, userSelectedView) => {
                // if userSelectedView is null then we must be loading an insight
                // and, we can prefer a present query over a present filter
                // otherwise we can have both a filter and a query and without userSelectedView we don't know which to use
                // so, if there is a user selected view, we use that
                // this gets much simpler once everything is using queries

                if (userSelectedView === null) {
                    if (query) {
                        if (containsHogQLQuery(query)) {
                            return InsightType.SQL
                        } else if (isInsightVizNode(query)) {
                            return insightMap[query.source.kind] || InsightType.TRENDS
                        } else {
                            return InsightType.JSON
                        }
                    } else {
                        return filters.insight || InsightType.TRENDS
                    }
                } else {
                    return userSelectedView
                }
            },
        ],
        tabs: [
            (s) => [s.activeView],
            (activeView) => {
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

                tabs.push({
                    label: (
                        <>
                            SQL
                            <LemonTag type="warning" className="uppercase ml-2">
                                Beta
                            </LemonTag>
                        </>
                    ),
                    type: InsightType.SQL,
                    dataAttr: 'insight-sql-tab',
                })

                if (activeView === InsightType.JSON) {
                    // only display this tab when it is selected by the provided insight query
                    // don't display it otherwise... humans shouldn't be able to click to select this tab
                    // it only opens when you click the <OpenEditorButton/>
                    tabs.push({
                        label: (
                            <>
                                Custom{' '}
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
            if ([InsightType.SQL, InsightType.JSON].includes(view as InsightType)) {
                // if the selected view is SQL or JSON then we must have the "allow queries" flag on,
                // so no need to check it
                if (view === InsightType.JSON) {
                    actions.setQuery(TotalEventsTable)
                } else if (view === InsightType.SQL) {
                    const biVizFlag = Boolean(values.featureFlags[FEATURE_FLAGS.BI_VIZ])
                    actions.setQuery(biVizFlag ? examples.DataVisualization : examples.HogQLTable)
                }
            } else {
                let query: InsightVizNode

                if (view === InsightType.TRENDS) {
                    query = queryFromKind(NodeKind.TrendsQuery, values.filterTestAccountsDefault)
                } else if (view === InsightType.FUNNELS) {
                    query = queryFromKind(NodeKind.FunnelsQuery, values.filterTestAccountsDefault)
                } else if (view === InsightType.RETENTION) {
                    query = queryFromKind(NodeKind.RetentionQuery, values.filterTestAccountsDefault)
                } else if (view === InsightType.PATHS) {
                    query = queryFromKind(NodeKind.PathsQuery, values.filterTestAccountsDefault)
                } else if (view === InsightType.STICKINESS) {
                    query = queryFromKind(NodeKind.StickinessQuery, values.filterTestAccountsDefault)
                } else if (view === InsightType.LIFECYCLE) {
                    query = queryFromKind(NodeKind.LifecycleQuery, values.filterTestAccountsDefault)
                } else {
                    throw new Error('encountered unexpected type for view')
                }

                actions.setQuery({
                    ...query,
                    source: values.queryPropertyCache
                        ? mergeCachedProperties(query.source, values.queryPropertyCache)
                        : query.source,
                } as InsightVizNode)
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

    // set series (first two entries) from retention target and returning entity
    if (isRetentionQuery(query)) {
        const { target_entity, returning_entity } = query.retentionFilter || {}
        const series = actionsAndEventsToSeries({
            events: [
                ...(target_entity?.type === 'events' ? [target_entity as ActionFilter] : []),
                ...(returning_entity?.type === 'events' ? [returning_entity as ActionFilter] : []),
            ],
            actions: [
                ...(target_entity?.type === 'actions' ? [target_entity as ActionFilter] : []),
                ...(returning_entity?.type === 'actions' ? [returning_entity as ActionFilter] : []),
            ],
        })
        if (series.length > 0) {
            newCache.series = [...series, ...(cache?.series ? cache.series.slice(series.length) : [])]
        }
    }

    // store the insight specific filter in commonFilter
    const filterKey = filterKeyForQuery(query)
    newCache.commonFilter = { ...cache?.commonFilter, ...query[filterKey] }

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
            mergedQuery.series = cache.series
        } else if (cache.retentionFilter?.target_entity || cache.retentionFilter?.returning_entity) {
            mergedQuery.series = [
                ...(cache.retentionFilter.target_entity
                    ? [cache.retentionFilter.target_entity as EventsNode | ActionsNode]
                    : []),
                ...(cache.retentionFilter.returning_entity
                    ? [cache.retentionFilter.returning_entity as EventsNode | ActionsNode]
                    : []),
            ]
        }
    } else if (isRetentionQuery(mergedQuery) && cache.series) {
        mergedQuery.retentionFilter = {
            ...mergedQuery.retentionFilter,
            ...(cache.series.length > 0 ? { target_entity: cache.series[0] } : {}),
            ...(cache.series.length > 1 ? { returning_entity: cache.series[1] } : {}),
        }
    }

    // interval
    if (isInsightQueryWithSeries(mergedQuery) && cache.interval) {
        mergedQuery.interval = cache.interval
    }

    // breakdown
    if (isInsightQueryWithBreakdown(mergedQuery) && cache.breakdown) {
        mergedQuery.breakdown = cache.breakdown
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
            ...(getShowValueOnSeries(node) ? { show_values_on_series: getShowValueOnSeries(node) } : {}),
            ...(getShowPercentStackView(node) ? { show_percent_stack_view: getShowPercentStackView(node) } : {}),
            ...(getDisplay(node) ? { display: getDisplay(node) } : {}),
        }
    }

    return mergedQuery
}
