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
import { isInsightVizNode } from '~/queries/utils'
import { TotalEventsTable } from '~/queries/examples'

export interface Tab {
    label: string
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
        activeView: [
            (s) => [s.filters, s.query, s.isUsingDataExploration],
            (filters, query, isUsingDataExploration) => {
                if (isUsingDataExploration) {
                    if (isInsightVizNode(query)) {
                        return insightMap[query.source.kind] || InsightType.TRENDS
                    } else if (!!query) {
                        return InsightType.QUERY
                    } else {
                        return InsightType.TRENDS
                    }
                } else {
                    return filters.insight || InsightType.TRENDS
                }
            },
        ],
        tabs: [
            (s) => [s.isUsingDataExploration],
            (isUsingDataExploration) => {
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

                if (isUsingDataExploration) {
                    tabs.push({
                        label: 'Query',
                        type: InsightType.QUERY,
                        dataAttr: 'insight-query-tab',
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
                } else if (view === InsightType.QUERY) {
                    actions.setQuery(TotalEventsTable)
                }
            } else {
                actions.setFilters(
                    cleanFilters(
                        // double-check that the view is valid
                        { ...values.filters, insight: view === InsightType.QUERY ? InsightType.TRENDS : view },
                        values.filters
                    )
                )
            }
        },
    })),
])
