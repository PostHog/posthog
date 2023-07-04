import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { FilterType, InsightLogicProps, InsightType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { DataNode, InsightNodeKind, InsightVizNode, Node, NodeKind } from '~/queries/schema'

import type { insightDataLogicType } from './insightDataLogicType'
import { insightLogic } from './insightLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { isInsightVizNode } from '~/queries/utils'
import { cleanFilters } from './utils/cleanFilters'
import { insightTypeToDefaultQuery, nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { queryExportContext } from '~/queries/query'
import { objectsEqual } from 'lib/utils'
import { compareFilters } from './utils/compareFilters'
import { filterTestAccountsDefaultsLogic } from 'scenes/project/Settings/filterTestAccountDefaultsLogic'
import { insightDataTimingLogic } from './insightDataTimingLogic'

const queryFromFilters = (filters: Partial<FilterType>): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: filtersToQueryNode(filters),
})

export const queryFromKind = (kind: InsightNodeKind, filterTestAccountsDefault: boolean): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: { ...nodeKindToDefaultQuery[kind], ...(filterTestAccountsDefault ? { filterTestAccounts: true } : {}) },
})

export const insightDataLogic = kea<insightDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic,
            ['filters', 'insight', 'savedInsight'],
            // TODO: need to pass empty query here, as otherwise dataNodeLogic will throw
            dataNodeLogic({ key: insightVizDataNodeKey(props), query: {} as DataNode }),
            [
                'dataLoading as insightDataLoading',
                'responseErrorObject as insightDataError',
                'getInsightRefreshButtonDisabledReason',
            ],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
        ],
        actions: [
            insightLogic,
            ['setInsight', 'loadInsightSuccess', 'saveInsight as insightLogicSaveInsight'],
            // TODO: need to pass empty query here, as otherwise dataNodeLogic will throw
            dataNodeLogic({ key: insightVizDataNodeKey(props), query: {} as DataNode }),
            ['loadData'],
        ],
        logic: [insightDataTimingLogic(props)],
    })),

    actions({
        setQuery: (query: Node | null) => ({ query }),
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        toggleQueryEditorPanel: true,
        cancelChanges: true,
    }),

    reducers({
        internalQuery: [
            null as Node | null,
            {
                setQuery: (_, { query }) => query,
            },
        ],
        showQueryEditor: [
            false,
            {
                toggleQueryEditorPanel: (state) => !state,
            },
        ],
    }),

    selectors({
        query: [
            (s) => [s.filters, s.insight, s.internalQuery, s.filterTestAccountsDefault],
            (filters, insight, internalQuery, filterTestAccountsDefault) =>
                internalQuery ||
                insight.query ||
                (filters && filters.insight ? queryFromFilters(filters) : undefined) ||
                queryFromKind(NodeKind.TrendsQuery, filterTestAccountsDefault),
        ],

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
            (s) => [s.isQueryBasedInsight, s.query, s.insight, s.savedInsight],
            (isQueryBasedInsight, query, insight, savedInsight) => {
                if (isQueryBasedInsight) {
                    return !objectsEqual(query, insight.query)
                } else {
                    const currentFilters = queryNodeToFilter((query as InsightVizNode).source)
                    const savedFilters =
                        savedInsight.filters ||
                        queryNodeToFilter(insightTypeToDefaultQuery[currentFilters.insight || InsightType.TRENDS])

                    // TODO: Ignore filter_test_accounts for now, but should compare against default
                    delete currentFilters.filter_test_accounts
                    delete savedFilters.filter_test_accounts

                    return !compareFilters(currentFilters, savedFilters)
                }
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
        saveInsight: ({ redirectToViewMode }) => {
            let filters = values.insight.filters
            if (isInsightVizNode(values.query)) {
                const querySource = values.query.source
                filters = queryNodeToFilter(querySource)
            } else if (values.isQueryBasedInsight) {
                filters = {}
            }

            let query = undefined
            if (values.isQueryBasedInsight) {
                query = values.query
            }

            actions.setInsight(
                {
                    ...values.insight,
                    filters: filters,
                    query: query ?? undefined,
                },
                { overrideFilter: true, fromPersistentApi: false }
            )

            actions.insightLogicSaveInsight(redirectToViewMode)
        },
        cancelChanges: () => {
            const savedFilters = values.savedInsight.filters
            actions.setQuery(savedFilters ? queryFromFilters(savedFilters) : null)
        },
    })),
    propsChanged(({ actions, props, values }) => {
        if (props.cachedInsight?.query && !objectsEqual(props.cachedInsight.query, values.query)) {
            actions.setQuery(props.cachedInsight.query)
        }
    }),
])
