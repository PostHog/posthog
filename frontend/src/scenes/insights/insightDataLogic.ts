import { kea, props, key, path, actions, reducers, selectors, connect, listeners } from 'kea'
import { InsightLogicProps, InsightType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema'
import { BaseMathType } from '~/types'
import { ShownAsValue } from 'lib/constants'

import type { insightDataLogicType } from './insightDataLogicType'
import { insightLogic } from './insightLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/queryNodeToFilter'
import { isLifecycleQuery } from '~/queries/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const getDefaultQuery = (kind: NodeKind.LifecycleQuery | NodeKind.UnimplementedQuery): InsightVizNode => {
    if (kind == NodeKind.LifecycleQuery) {
        return {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.LifecycleQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                        math: BaseMathType.TotalCount,
                    },
                ],
                lifecycleFilter: { shown_as: ShownAsValue.LIFECYCLE },
            },
        }
    } else {
        return {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.UnimplementedQuery,
            },
        }
    }
}

export const insightDataLogic = kea<insightDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    connect({
        actions: [insightLogic, ['setFilters', 'setActiveView']],
        values: [featureFlagLogic, ['featureFlags']],
    }),

    actions({
        setQuery: (query: InsightVizNode) => ({ query }),
        setQuerySourceMerge: (query: Omit<Partial<InsightQueryNode>, 'kind'>) => ({ query }),
    }),

    reducers({
        query: [
            // TODO load from cachedInsight?.filters
            // () => props.cachedInsight?.filters || ({} as Partial<FilterType>),
            getDefaultQuery(NodeKind.UnimplementedQuery) as InsightVizNode,
            {
                setQuery: (_, { query }) => query,
            },
        ],
    }),

    selectors({
        querySource: [(s) => [s.query], (query) => query.source],
    }),

    listeners(({ actions, values }) => ({
        setQuerySourceMerge: ({ query }) => {
            actions.setQuery({ ...values.query, source: { ...values.query.source, ...query } })
        },
        setQuery: ({ query }) => {
            // safeguard against accidentally overwriting filters for non-flagged users
            if (values.featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]) {
                return
            }

            if (isLifecycleQuery(query.source)) {
                const filters = queryNodeToFilter(query.source)
                actions.setFilters(filters)
            }
        },
        setActiveView: ({ type }) => {
            // TODO: make a getCleanedQuery function that takes the existing values.query and
            // sets parameters from previous view similar to
            // cleanFilters({ ...values.filters, insight: type as InsightType }, values.filters)
            if (type === InsightType.LIFECYCLE) {
                actions.setQuery(getDefaultQuery(NodeKind.LifecycleQuery))
            } else {
                actions.setQuery(getDefaultQuery(NodeKind.UnimplementedQuery))
            }
        },
    })),
])
