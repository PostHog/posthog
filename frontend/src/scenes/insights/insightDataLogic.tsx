import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { DATAWAREHOUSE_EDITOR_ITEM_ID } from 'scenes/data-warehouse/external/dataWarehouseExternalSceneLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'

import { examples } from '~/queries/examples'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { insightMap } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { queryExportContext } from '~/queries/query'
import {
    DataTableNode,
    DataVisualizationNode,
    HogQuery,
    InsightNodeKind,
    InsightVizNode,
    Node,
    NodeKind,
} from '~/queries/schema'
import { isDataTableNode, isDataVisualizationNode, isHogQuery, isInsightVizNode } from '~/queries/utils'
import { ExportContext, FilterType, InsightLogicProps, InsightType } from '~/types'

import type { insightDataLogicType } from './insightDataLogicType'
import { insightDataTimingLogic } from './insightDataTimingLogic'
import { insightLogic } from './insightLogic'
import { insightUsageLogic } from './insightUsageLogic'
import { compareQuery } from './utils/queryUtils'

export const queryFromFilters = (filters: Partial<FilterType>): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: filtersToQueryNode(filters),
})

export const getDefaultQuery = (
    insightType: InsightType,
    filterTestAccountsDefault: boolean
): DataTableNode | DataVisualizationNode | HogQuery | InsightVizNode => {
    if ([InsightType.SQL, InsightType.JSON, InsightType.HOG].includes(insightType)) {
        if (insightType === InsightType.JSON) {
            return examples.TotalEventsTable as DataTableNode
        } else if (insightType === InsightType.SQL) {
            return examples.DataVisualization as DataVisualizationNode
        } else if (insightType === InsightType.HOG) {
            return examples.Hoggonacci as HogQuery
        }
    } else {
        if (insightType === InsightType.TRENDS) {
            return queryFromKind(NodeKind.TrendsQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.FUNNELS) {
            return queryFromKind(NodeKind.FunnelsQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.RETENTION) {
            return queryFromKind(NodeKind.RetentionQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.PATHS) {
            return queryFromKind(NodeKind.PathsQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.STICKINESS) {
            return queryFromKind(NodeKind.StickinessQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.LIFECYCLE) {
            return queryFromKind(NodeKind.LifecycleQuery, filterTestAccountsDefault)
        }
    }

    throw new Error('encountered unexpected type for view')
}

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
        toggleDebugPanel: true,
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
        showDebugPanel: [
            false,
            {
                toggleDebugPanel: (state) => !state,
            },
        ],
    }),

    selectors({
        useQueryDashboardCards: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.QUERY_BASED_DASHBOARD_CARDS],
        ],

        query: [
            (s) => [s.propsQuery, s.insight, s.internalQuery, s.filterTestAccountsDefault, s.isDataWarehouseQuery],
            (propsQuery, insight, internalQuery, filterTestAccountsDefault, isDataWarehouseQuery): Node | null =>
                propsQuery ||
                internalQuery ||
                insight.query ||
                (isDataWarehouseQuery
                    ? examples.DataWarehouse
                    : queryFromKind(NodeKind.TrendsQuery, filterTestAccountsDefault)),
        ],

        isDataWarehouseQuery: [
            () => [(_, props) => props],
            (props: InsightLogicProps) => !!props.dashboardItemId?.startsWith(DATAWAREHOUSE_EDITOR_ITEM_ID),
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
            (s) => [s.query, s.savedInsight, s.filterTestAccountsDefault],
            (query, savedInsight, filterTestAccountsDefault) => {
                let savedOrDefaultQuery
                if (savedInsight.query) {
                    savedOrDefaultQuery = savedInsight.query as InsightVizNode | DataVisualizationNode
                } else if (isInsightVizNode(query)) {
                    savedOrDefaultQuery = getDefaultQuery(insightMap[query.source.kind], filterTestAccountsDefault)
                } else if (isDataVisualizationNode(query)) {
                    savedOrDefaultQuery = getDefaultQuery(InsightType.SQL, filterTestAccountsDefault)
                } else if (isDataTableNode(query)) {
                    savedOrDefaultQuery = getDefaultQuery(InsightType.JSON, filterTestAccountsDefault)
                } else if (isHogQuery(query)) {
                    savedOrDefaultQuery = getDefaultQuery(InsightType.HOG, filterTestAccountsDefault)
                } else {
                    return false
                }

                return !compareQuery(savedOrDefaultQuery, query as InsightVizNode | DataVisualizationNode)
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
            // we don't want to override the query for example when updating the insight's name
            if (!overrideQuery) {
                return
            }

            if (query) {
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
