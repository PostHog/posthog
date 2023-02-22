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
                    const q = isInsightVizNode(query) ? query.source : query
                    return insightMap[q.kind] || InsightType.TRENDS
                } else {
                    return filters.insight || InsightType.TRENDS
                }
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
                }
            } else {
                actions.setFilters(cleanFilters({ ...values.filters, insight: view as InsightType }, values.filters))
            }
        },
    })),
])
