import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightTypeToDefaultQuery, nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { queryExportContext } from '~/queries/query'
import { InsightNodeKind, InsightVizNode, Node, NodeKind } from '~/queries/schema'
import { isInsightVizNode } from '~/queries/utils'
import { ExportContext, FilterType, InsightLogicProps, InsightType } from '~/types'

import type { insightDataLogicType } from './insightDataLogicType'
import { insightDataTimingLogic } from './insightDataTimingLogic'
import { insightLogic } from './insightLogic'
import { insightUsageLogic } from './insightUsageLogic'
import { setTestAccountFilterForNewInsight } from './utils/cleanFilters'
import { compareFilters } from './utils/compareFilters'

export const queryFromFilters = (filters: Partial<FilterType>): InsightVizNode => ({
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
            ['insight', 'savedInsight'],
            dataNodeLogic({
                key: insightVizDataNodeKey(props),
                loadPriority: props.loadPriority,
            } as DataNodeLogicProps),
            [
                'query as insightQuery',
                'response as insightDataRaw',
                'dataLoading as insightDataLoading',
                'responseErrorObject as insightDataError',
                'getInsightRefreshButtonDisabledReason',
                'pollResponse as insightPollResponse',
                'queryId',
            ],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
            teamLogic,
            ['currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            insightLogic,
            ['setInsight', 'loadInsightSuccess'],
            dataNodeLogic({ key: insightVizDataNodeKey(props) } as DataNodeLogicProps),
            ['loadData', 'loadDataSuccess', 'loadDataFailure', 'setResponse as setInsightData'],
        ],
        logic: [insightDataTimingLogic(props), insightUsageLogic(props)],
    })),

    actions({
        setQuery: (query: Node | null) => ({ query }),
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
        useQueryDashboardCards: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.QUERY_BASED_DASHBOARD_CARDS],
        ],

        query: [
            (s) => [s.propsQuery, s.insight, s.internalQuery, s.filterTestAccountsDefault],
            (propsQuery, insight, internalQuery, filterTestAccountsDefault): Node | null =>
                propsQuery ||
                internalQuery ||
                insight.query ||
                queryFromKind(NodeKind.TrendsQuery, filterTestAccountsDefault),
        ],

        propsQuery: [
            () => [(_, props) => props],
            // overwrite query from props for standalone InsightVizNode queries
            (props: InsightLogicProps) => (props.dashboardItemId?.startsWith('new-AdHoc.') ? props.query : null),
        ],

        exportContext: [
            (s) => [s.query, s.insight],
            (query, insight) => {
                if (!query) {
                    // if we're here without a query then an empty query context is not the problem
                    return undefined
                }
                const filename = ['export', insight.name || insight.derived_name].join('-')

                let sourceQuery = query
                if (isInsightVizNode(query)) {
                    sourceQuery = query.source
                }

                return {
                    ...queryExportContext(sourceQuery, undefined, undefined),
                    filename,
                } as ExportContext
            },
        ],

        queryChanged: [
            (s) => [s.query, s.savedInsight, s.currentTeam],
            (query, savedInsight, currentTeam) => {
                if (savedInsight.query && !isInsightVizNode(savedInsight.query)) {
                    // saved non-insight query
                    return !objectsEqual(query, savedInsight.query)
                } else if (savedInsight.query && isInsightVizNode(savedInsight.query)) {
                    // saved insight query
                    if (!isInsightVizNode(query)) {
                        return true
                    }

                    const currentFilters = queryNodeToFilter(query.source)
                    const savedFilters = queryNodeToFilter(savedInsight.query.source)

                    return !compareFilters(currentFilters, savedFilters)
                }

                // new insight
                if (!isInsightVizNode(query)) {
                    return true
                }

                const currentFilters = queryNodeToFilter(query.source)
                const savedFilters = queryNodeToFilter(
                    insightTypeToDefaultQuery[currentFilters.insight || InsightType.TRENDS]
                )
                setTestAccountFilterForNewInsight(savedFilters, currentTeam?.test_account_filters_default_checked)

                return !compareFilters(currentFilters, savedFilters, currentTeam?.test_account_filters_default_checked)
            },
        ],

        insightData: [
            (s) => [s.insightDataRaw],
            (insightDataRaw): Record<string, any> => {
                // :TRICKY: The queries return results as `results`, but insights expect `result`
                return { ...insightDataRaw, result: insightDataRaw?.results ?? insightDataRaw?.result }
            },
        ],

        hogQL: [
            (s) => [s.insightData],
            (insightData): string | null => {
                if (insightData && 'hogql' in insightData && insightData.hogql !== '') {
                    return insightData.hogql
                }
                return null
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setInsight: ({ insight: { query, result }, options: { overrideQuery } }) => {
            if (overrideQuery && query) {
                actions.setQuery(query)
            }

            if (result) {
                actions.setInsightData({ ...values.insightData, result })
            }
        },
        loadInsightSuccess: ({ insight }) => {
            if (insight.query) {
                actions.setQuery(insight.query)
            }
        },
        cancelChanges: () => {
            const savedQuery = values.savedInsight.query
            const savedResult = values.savedInsight.result
            actions.setQuery(savedQuery || null)
            actions.setInsightData({ ...values.insightData, result: savedResult ? savedResult : null })
        },
    })),
    propsChanged(({ actions, props, values }) => {
        if (props.cachedInsight?.query && !objectsEqual(props.cachedInsight.query, values.query)) {
            actions.setQuery(props.cachedInsight.query)
        }
    }),
])
