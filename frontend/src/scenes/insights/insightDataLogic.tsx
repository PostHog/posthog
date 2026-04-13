import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { objectsEqual } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DATAWAREHOUSE_EDITOR_ITEM_ID } from 'scenes/data-warehouse/utils'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { examples } from '~/queries/examples'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { nodeKindToInsightType } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getDefaultQuery, queryFromKind } from '~/queries/nodes/InsightViz/utils'
import { queryExportContext } from '~/queries/query'
import { DataVisualizationNode, HogQLVariable, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'
import {
    isDataTableNode,
    isDataVisualizationNode,
    isHogQLQuery,
    isHogQuery,
    isInsightQueryNode,
    isInsightVizNode,
    isWebAnalyticsInsightQuery,
    shouldQueryBeAsync,
} from '~/queries/utils'
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
            ['setInsight', 'setInsightMetadata'],
            dataNodeLogic({ key: insightVizDataNodeKey(props) } as DataNodeLogicProps),
            ['loadData', 'loadDataSuccess', 'loadDataFailure', 'setResponse as setInsightData'],
        ],
        logic: [insightDataTimingLogic(props), insightUsageLogic(props)],
    })),

    actions({
        setQuery: (query: Node | null) => ({ query }),
        syncQueryFromProps: (query: Node | null) => ({ query }),
        toggleQueryEditorPanel: true,
        toggleDebugPanel: true,
        cancelChanges: true,
    }),

    reducers({
        internalQuery: [
            null as Node | null,
            {
                setQuery: (_, { query }) => query,
                syncQueryFromProps: (_, { query }) => query,
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

    loaders(({ values }) => ({
        generatedInsightMetadata: [
            null as { name: string; description: string } | null,
            {
                generateInsightMetadata: async () => {
                    const insightQuery = values.insightQuery
                    if (!insightQuery) {
                        return null
                    }

                    try {
                        const query =
                            insightQuery.kind === NodeKind.ActorsQuery ||
                            insightQuery.kind === NodeKind.EventsQuery ||
                            insightQuery.kind === NodeKind.GroupsQuery
                                ? insightQuery
                                : { kind: NodeKind.InsightVizNode, source: insightQuery }
                        const response = await api.insights.generateMetadata(query)

                        eventUsageLogic.actions.reportInsightMetadataAiGenerated(insightQuery.kind)

                        return { name: response.name, description: response.description }
                    } catch (e) {
                        eventUsageLogic.actions.reportInsightMetadataAiGenerationFailed(insightQuery.kind)
                        lemonToast.error('Failed to generate name and description')
                        throw e
                    }
                },
            },
        ],
    })),

    selectors({
        query: [
            (s) => [s.propsQuery, s.insight, s.internalQuery, s.filterTestAccountsDefault, s.isDataWarehouseQuery],
            (propsQuery, insight, internalQuery, filterTestAccountsDefault, isDataWarehouseQuery): Node | null =>
                internalQuery ||
                propsQuery ||
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
                    // Web Analytics insights don't have traditional defaults, they come from tiles
                    // and should always be considered "changed" for URL hash purposes
                    if (isWebAnalyticsInsightQuery(query.source)) {
                        return true
                    }
                    const insightType = nodeKindToInsightType[query.source.kind]
                    savedOrDefaultQuery = getDefaultQuery(insightType, filterTestAccountsDefault)
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
        canEditInSqlEditor: [
            (s) => [s.hogQL, s.query],
            (hogQL, query): boolean =>
                // We need a resolved hogql string, and the insight must not already be SQL-authored
                // (otherwise "Edit in SQL editor" is a no-op).
                hogQL != null &&
                !isHogQLQuery(query) &&
                !(isDataVisualizationNode(query) && isHogQLQuery(query.source)),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        generateInsightMetadataSuccess: ({ generatedInsightMetadata }) => {
            if (generatedInsightMetadata) {
                actions.setInsightMetadata({
                    name: generatedInsightMetadata.name,
                    description: generatedInsightMetadata.description,
                })
                if (generatedInsightMetadata.description && !sceneLayoutLogic.values.showDescription) {
                    sceneLayoutLogic.actions.toggleShowDescription()
                }
            }
        },
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
    propsChanged(({ actions, props, values }, oldProps) => {
        // Uses syncQueryFromProps (not setQuery) to avoid triggering the
        // insightVizDataLogic.setQuery listener which would loop back via props.setQuery.
        // Guard must match propsQuery selector (only ad-hoc insights receive query via props).
        if (props.dashboardItemId?.startsWith('new-AdHoc.') && props.query) {
            try {
                if (!objectsEqual(props.query, values.query)) {
                    actions.syncQueryFromProps(props.query)
                }
            } catch {
                actions.syncQueryFromProps(props.query)
            }
            return
        }

        if (!props.cachedInsight?.query) {
            return
        }

        const cachedQueryChanged =
            !oldProps?.cachedInsight?.query || !objectsEqual(oldProps.cachedInsight.query, props.cachedInsight.query)

        if (!cachedQueryChanged) {
            return
        }
        try {
            if (!objectsEqual(props.cachedInsight.query, values.query)) {
                actions.setQuery(props.cachedInsight.query)
            }
        } catch {
            // values.query can throw if the logic's state isn't in the store yet
            // (e.g. when InsightCard rebuilds the logic during navigation)
            actions.setQuery(props.cachedInsight.query)
        }
    }),
    afterMount(({ actions, props }) => {
        // On a dashboard, the first response for a tile can say “we don’t have chart numbers yet”
        // (`result: null`) instead of leaving the field unset. Without a real fetch, the UI can look
        // like a failed load (“Chart data didn’t load”) even though we simply haven’t run the query.
        // Force-refresh here for dashboard-backed insights only so we don’t change generic data-node behavior.
        if (props.doNotLoad || props.dashboardId == null) {
            return
        }
        const cached = props.cachedInsight
        if (!cached || typeof cached !== 'object') {
            return
        }
        const cr = cached as Record<string, unknown>
        const hasRenderable =
            (cr.result !== null && cr.result !== undefined) || (cr.results !== null && cr.results !== undefined)
        if (hasRenderable) {
            return
        }
        const iq = cached.query
        if (!iq || !isInsightVizNode(iq)) {
            return
        }
        const source = iq.source
        if (isInsightQueryNode(source)) {
            if (isWebAnalyticsInsightQuery(source)) {
                return
            }
            actions.loadData(shouldQueryBeAsync(source) ? 'force_async' : 'force_blocking')
        } else if (isHogQLQuery(source)) {
            actions.loadData('force_blocking')
        }
    }),
    actionToUrl(({ props }) => ({
        cancelChanges: () => {
            if (props.tabId && sceneLogic.values.activeTabId === props.tabId) {
                const { pathname, searchParams, hashParams } = router.values.currentLocation
                const { q: _, ...hash } = hashParams
                return [pathname, searchParams, hash]
            }
        },
    })),
])
