import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { InsightLogicProps, InsightType } from '~/types'

import type { insightNavLogicType } from './insightNavLogicType'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import {
    ActionsNode,
    EventsNode,
    FunnelsQuery,
    InsightQueryNode,
    InsightVizNode,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema'
import { insightDataLogic, queryFromKind } from 'scenes/insights/insightDataLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightMap } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import {
    containsHogQLQuery,
    filterKeyForQuery,
    isInsightQueryWithBreakdown,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isRetentionQuery,
} from '~/queries/utils'
import { examples, TotalEventsTable } from '~/queries/examples'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { filterTestAccountsDefaultsLogic } from 'scenes/project/Settings/filterTestAccountDefaultsLogic'

export interface Tab {
    label: string | JSX.Element
    type: InsightType
    dataAttr: string
}

interface QueryPropertyCache
    extends Omit<TrendsQuery, 'kind'>,
        Omit<FunnelsQuery, 'kind'>,
        Omit<RetentionQuery, 'kind'>,
        Omit<PathsQuery, 'kind'>,
        Omit<StickinessQuery, 'kind'>,
        Omit<LifecycleQuery, 'kind'> {}

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
        updateQueryPropertyCache: (cache: InsightQueryNode) => ({ cache }),
    }),
    reducers({
        queryPropertyCache: [
            null as QueryPropertyCache | null,
            {
                updateQueryPropertyCache: (state, { cache }) => ({ ...state, ...cache }),
            },
        ],
        userSelectedView: {
            setActiveView: (_, { view }) => view,
        },
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
            // TODO: move to subscription on query
            if (isInsightVizNode(values.query)) {
                // TODO: update series from retention query
                actions.updateQueryPropertyCache(values.query.source)
            }

            if ([InsightType.SQL, InsightType.JSON].includes(view as InsightType)) {
                // if the selected view is SQL or JSON then we must have the "allow queries" flag on,
                // so no need to check it
                if (view === InsightType.JSON) {
                    actions.setQuery(TotalEventsTable)
                } else if (view === InsightType.SQL) {
                    actions.setQuery(examples.HogQLTable)
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
                    source: mergeCachedProperties(query.source, values.queryPropertyCache),
                } as InsightVizNode)
            }
        },
    })),
])

const mergeCachedProperties = (query: InsightQueryNode, cache: QueryPropertyCache): InsightQueryNode => {
    // TODO: prevent merges when the query is of the same kind to allow resetting by clicking on the nav item

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
    } else if (isRetentionQuery(mergedQuery)) {
        mergedQuery.retentionFilter = {
            ...mergedQuery.retentionFilter,
            ...(cache.series?.length > 0 ? { target_entity: cache.series[0] } : {}),
            ...(cache.series?.length > 1 ? { returning_entity: cache.series[1] } : {}),
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
    if (cache[filterKey]) {
        // TODO: implement handling of shared properties
        mergedQuery[filterKey] = cache[filterKey]
    }

    return mergedQuery
}
