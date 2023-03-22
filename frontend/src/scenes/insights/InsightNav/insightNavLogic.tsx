import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { InsightLogicProps, InsightType } from '~/types'

import type { insightNavLogicType } from './insightNavLogicType'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { insightLogic } from 'scenes/insights/insightLogic'
import { NodeKind } from '~/queries/schema'
import { insightDataLogic, queryFromKind } from 'scenes/insights/insightDataLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { insightMap } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { containsHogQLQuery, isInsightVizNode } from '~/queries/utils'
import { examples, TotalEventsTable } from '~/queries/examples'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

export interface Tab {
    label: string | JSX.Element
    type: InsightType
    dataAttr: string
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
        ],
        actions: [insightLogic(props), ['setFilters'], insightDataLogic(props), ['setQuery']],
    })),
    actions({
        setActiveView: (view: InsightType) => ({ view }),
    }),
    reducers({
        userSelectedView: {
            setActiveView: (_, { view }) => view,
        },
    }),
    selectors({
        isUsingDataExploration: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_INSIGHTS],
        ],
        allowQueryTab: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_QUERY_TAB],
        ],
        activeView: [
            (s) => [s.filters, s.query, s.userSelectedView],
            (filters, query, userSelectedView) => {
                // if userSelectedView is null then we must be loading an insight
                // and, we can prefer a present query over a present filter
                // otherwise we can have both a filter and a query and without userSelectedView we don't know which to use
                // so, if there is a user selected view, we use that
                // this gets much simpler once everything is using queries

                if (userSelectedView === null) {
                    if (!!query) {
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
            (s) => [s.allowQueryTab, s.activeView],
            (allowQueryTab, activeView) => {
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

                if (allowQueryTab) {
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
                                    JSON{' '}
                                    <LemonTag type="warning" className="uppercase ml-2">
                                        Beta
                                    </LemonTag>
                                </>
                            ),
                            type: InsightType.JSON,
                            dataAttr: 'insight-json-tab',
                        })
                    }
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
                    actions.setQuery(examples.HogQLTable)
                }
            } else {
                if (values.isUsingDataExploration) {
                    if (view === InsightType.TRENDS) {
                        actions.setQuery(queryFromKind(NodeKind.TrendsQuery))
                    } else if (view === InsightType.FUNNELS) {
                        actions.setQuery(queryFromKind(NodeKind.FunnelsQuery))
                    } else if (view === InsightType.RETENTION) {
                        actions.setQuery(queryFromKind(NodeKind.RetentionQuery))
                    } else if (view === InsightType.PATHS) {
                        actions.setQuery(queryFromKind(NodeKind.PathsQuery))
                    } else if (view === InsightType.STICKINESS) {
                        actions.setQuery(queryFromKind(NodeKind.StickinessQuery))
                    } else if (view === InsightType.LIFECYCLE) {
                        actions.setQuery(queryFromKind(NodeKind.LifecycleQuery))
                    }
                } else {
                    actions.setFilters(
                        cleanFilters(
                            // double-check that the view is valid
                            { ...values.filters, insight: view || InsightType.TRENDS },
                            values.filters
                        ),
                        undefined,
                        true
                    )
                }
            }
        },
    })),
])
