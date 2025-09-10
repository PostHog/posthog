import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { objectsEqual } from 'lib/utils'
import { DATAWAREHOUSE_EDITOR_ITEM_ID } from 'scenes/data-warehouse/utils'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { examples } from '~/queries/examples'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { nodeKindToInsightType } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getDefaultQuery, queryFromKind } from '~/queries/nodes/InsightViz/utils'
import { queryExportContext } from '~/queries/query'
import { DataVisualizationNode, HogQLVariable, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { isDataTableNode, isDataVisualizationNode, isHogQLQuery, isHogQuery, isInsightVizNode } from '~/queries/utils'
import { ExportContext, InsightLogicProps, InsightType } from '~/types'

import { teamLogic } from '../teamLogic'
import type { insightDataLogicType } from './insightDataLogicType'
import { insightDataTimingLogic } from './insightDataTimingLogic'
import { insightLogic } from './insightLogic'
import { insightSceneLogic } from './insightSceneLogic'
import { insightUsageLogic } from './insightUsageLogic'
import { crushDraftQueryForLocalStorage, isQueryTooLarge } from './utils'
import { compareQuery } from './utils/queryUtils'

export const insightDataLogic = kea<insightDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic,
            ['insight', 'savedInsight'],
            teamLogic,
            ['currentTeamId'],
            dataNodeLogic({
                key: insightVizDataNodeKey(props),
                loadPriority: props.loadPriority,
                filtersOverride: props.filtersOverride,
                variablesOverride: props.variablesOverride,
            } as DataNodeLogicProps),
            [
                'query as insightQuery',
                'response as insightDataRaw',
                'dataLoading as insightDataLoading',
                'loadingTimeSeconds as insightLoadingTimeSeconds',
                'responseErrorObject as insightDataError',
                'getInsightRefreshButtonDisabledReason',
                'pollResponse as insightPollResponse',
                'queryId',
            ],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
        ],
        actions: [
            insightLogic,
            ['setInsight'],
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
                    savedOrDefaultQuery = getDefaultQuery(
                        nodeKindToInsightType[query.source.kind],
                        filterTestAccountsDefault
                    )
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
                return {
                    ...insightDataRaw,
                    result: (insightDataRaw as any)?.results ?? (insightDataRaw as any)?.result,
                }
            },
        ],

        hogQL: [
            (s) => [s.insightData, s.query],
            (insightData, query): string | null => {
                // Try to get it from the query itself, so we don't have to wait for the response
                if (isDataVisualizationNode(query) && isHogQLQuery(query.source)) {
                    return query.source.query
                }
                if (isHogQLQuery(query)) {
                    return query.query
                }
                // Otherwise, get it from the response
                if (insightData && 'hogql' in insightData && insightData.hogql !== '') {
                    return insightData.hogql
                }
                return null
            },
        ],
        hogQLVariables: [
            (s) => [s.query],
            (query): Record<string, HogQLVariable> | undefined => {
                if (isDataVisualizationNode(query) && isHogQLQuery(query.source)) {
                    return query.source.variables
                }
                if (isHogQLQuery(query)) {
                    return query.variables
                }
                return undefined
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
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
        cancelChanges: () => {
            const savedQuery = values.savedInsight.query
            const savedResult = values.savedInsight.result
            actions.setQuery(savedQuery || null)
            actions.setInsightData({ ...values.insightData, result: savedResult ? savedResult : null })
        },
        setQuery: ({ query }) => {
            // If we have a tabId, then this is an insight scene on a tab. Sync the query to the URL
            if (props.tabId && sceneLogic.values.activeTabId === props.tabId) {
                const insightId = insightSceneLogic.findMounted({ tabId: props.tabId })?.values.insightId
                const { pathname, searchParams, hashParams } = router.values.currentLocation
                if (query && (values.queryChanged || insightId === 'new' || insightId?.startsWith('new-'))) {
                    const { insight: _, ...hash } = hashParams // remove existing /new#insight=TRENDS param
                    router.actions.replace(pathname, searchParams, {
                        ...hash,
                        q: query,
                    })
                } else {
                    const { q: _, ...hash } = hashParams // remove existing insight query hash param
                    router.actions.replace(pathname, searchParams, hash)
                }
            }

            // if the query is not changed, don't save it
            if (!query || !values.queryChanged) {
                return
            }

            // only run on insight scene
            if (sceneLogic.values.activeSceneId !== Scene.Insight) {
                return
            }

            // don't save for saved insights
            if (props.tabId && sceneLogic.values.activeTabId === props.tabId) {
                const insightId = insightSceneLogic.findMounted({ tabId: props.tabId })?.values.insightId
                if (insightId && insightId !== 'new' && !insightId.startsWith('new-')) {
                    return
                }
            }

            if (isQueryTooLarge(query)) {
                localStorage.removeItem(`draft-query-${values.currentTeamId}`)
            }

            localStorage.setItem(
                `draft-query-${values.currentTeamId}`,
                crushDraftQueryForLocalStorage(query, Date.now())
            )
        },
    })),
    propsChanged(({ actions, props, values }) => {
        if (props.cachedInsight?.query && !objectsEqual(props.cachedInsight.query, values.query)) {
            actions.setQuery(props.cachedInsight.query)
        }
    }),
])
