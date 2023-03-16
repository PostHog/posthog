import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { FilterType, InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { DataNode, InsightNodeKind, InsightVizNode, Node, NodeKind } from '~/queries/schema'

import type { insightDataLogicType } from './insightDataLogicType'
import { insightLogic } from './insightLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { isInsightVizNode } from '~/queries/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cleanFilters } from './utils/cleanFilters'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { subscriptions } from 'kea-subscriptions'
import { queryExportContext } from '~/queries/query'
import { objectsEqual } from 'lib/utils'

const queryFromFilters = (filters: Partial<FilterType>): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: filtersToQueryNode(filters),
})

export const queryFromKind = (kind: InsightNodeKind): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: nodeKindToDefaultQuery[kind],
})

export const insightDataLogic = kea<insightDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic,
            ['insight', 'isUsingDataExploration'],
            featureFlagLogic,
            ['featureFlags'],
            // TODO: need to pass empty query here, as otherwise dataNodeLogic will throw
            dataNodeLogic({ key: insightVizDataNodeKey(props), query: {} as DataNode }),
            ['response as insightData'],
        ],
        actions: [
            insightLogic,
            ['setInsight', 'loadInsightSuccess', 'loadResultsSuccess', 'saveInsight as insightLogicSaveInsight'],
        ],
    })),

    actions({
        setQuery: (query: Node) => ({ query }),
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
    }),

    reducers(() => ({
        query: [
            null as Node | null,
            {
                setQuery: (_, { query }) => query,
            },
        ],
    })),

    selectors({
        isQueryBasedInsight: [
            (s) => [s.query],
            (query) => {
                return !!query && !isInsightVizNode(query)
            },
        ],

        exportContext: [
            (s) => [s.query, s.insight],
            (query, insight) => {
                if (!query) {
                    // if we're here without a query then an empty query context is not the problem
                    return undefined
                }
                const filename = ['export', insight.name || insight.derived_name].join('-')
                return { ...queryExportContext(query), filename }
            },
        ],

        queryChanged: [
            (s) => [s.query, s.insight],
            (query, insight) => {
                return !objectsEqual(query, insight.query)
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setInsight: ({ insight: { filters, query }, options: { overrideFilter } }) => {
            if (overrideFilter && query == null) {
                actions.setQuery(queryFromFilters(cleanFilters(filters || {})))
            } else if (query) {
                actions.setQuery(query)
            }
        },
        loadInsightSuccess: ({ insight }) => {
            if (!!insight.query) {
                actions.setQuery(insight.query)
            } else if (!!insight.filters && !!Object.keys(insight.filters).length) {
                const query = queryFromFilters(insight.filters)
                actions.setQuery(query)
            }
        },
        loadResultsSuccess: ({ insight }) => {
            if (!!insight.query) {
                actions.setQuery(insight.query)
            } else if (!!insight.filters && !!Object.keys(insight.filters).length) {
                const query = queryFromFilters(insight.filters)
                actions.setQuery(query)
            }
        },
        saveInsight: ({ redirectToViewMode }) => {
            if (!values.query) {
                return
            }

            let filters = values.insight.filters
            if (isInsightVizNode(values.query)) {
                const querySource = values.query.source
                filters = queryNodeToFilter(querySource)
            } else if (values.isQueryBasedInsight) {
                filters = {}
            }

            actions.setInsight(
                {
                    ...values.insight,
                    filters: filters,
                    ...(values.isQueryBasedInsight ? { query: values.query } : {}),
                },
                { overrideFilter: true, fromPersistentApi: false }
            )
            actions.insightLogicSaveInsight(redirectToViewMode)
        },
    })),
    subscriptions(
        ({
            values,
            // actions
        }) => ({
            /**
             * This subscription updates the insight for all visualizations
             * that haven't been refactored to use the data exploration yet.
             */
            insightData: () =>
                // insightData: Record<string, any> | null
                {
                    if (!values.isUsingDataExploration) {
                        return
                    }

                    // actions.setInsight(
                    //     {
                    //         ...values.insight,
                    //         result: insightData?.result,
                    //         next: insightData?.next,
                    //         filters: isInsightQueryNode(values.querySource) ? queryNodeToFilter(values.querySource) : {},
                    //     },
                    //     {}
                    // )
                    // TODO should anything happen here
                },
        })
    ),
])
