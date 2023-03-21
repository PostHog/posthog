import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
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
import { isDataTableNode, isHogQLQuery, isInsightVizNode } from '~/queries/utils'
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
    selectors({
        isUsingDataExploration: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_INSIGHTS],
        ],
        allowQueryTab: [
            (s) => [s.featureFlags, s.isUsingDataExploration],
            (featureFlags, isUsingDataExploration) =>
                isUsingDataExploration && !!featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_QUERY_TAB],
        ],
        activeView: [
            (s) => [s.filters, s.query, s.isUsingDataExploration],
            (filters, query, isUsingDataExploration) => {
                if (isUsingDataExploration) {
                    if (isInsightVizNode(query)) {
                        return insightMap[query.source.kind] || InsightType.TRENDS
                    } else if (!!query) {
                        if (isHogQLQuery(query) || (isDataTableNode(query) && isHogQLQuery(query.source))) {
                            return InsightType.SQL
                        }
                        return InsightType.JSON
                    } else {
                        return InsightType.TRENDS
                    }
                } else {
                    return filters.insight || InsightType.TRENDS
                }
            },
        ],
        tabs: [
            (s) => [s.allowQueryTab],
            (allowQueryTab) => {
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

                return tabs
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        setActiveView: ({ view }) => {
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
                } else if (view === InsightType.JSON) {
                    actions.setQuery(TotalEventsTable)
                } else if (view === InsightType.SQL) {
                    actions.setQuery(examples.HogQLTable)
                }
            } else {
                actions.setFilters(
                    cleanFilters(
                        // double-check that the view is valid
                        { ...values.filters, insight: view === InsightType.JSON ? InsightType.TRENDS : view },
                        values.filters
                    )
                )
            }
        },
    })),
])
