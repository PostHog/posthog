import {
    actions,
    afterMount,
    connect,
    isBreakpoint,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { objectsEqual } from 'lib/utils/objects'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightsApi } from 'scenes/insights/utils/api'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { insightsModel } from '~/models/insightsModel'
import { examples } from '~/queries/examples'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { nodeKindToInsightType } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
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

import { DATAWAREHOUSE_EDITOR_ITEM_ID } from 'products/data_warehouse/frontend/utils'

import { teamLogic } from '../teamLogic'
import type { insightDataLogicType } from './insightDataLogicType'
import { insightDataTimingLogic } from './insightDataTimingLogic'
import { insightLogic } from './insightLogic'
import { insightSceneLogic } from './insightSceneLogic'
import { insightUsageLogic } from './insightUsageLogic'
import { crushDraftQueryForLocalStorage, isQueryTooLarge } from './utils'
import { compareQuery } from './utils/queryUtils'

export const isInsightSceneInstance = (props: InsightLogicProps): boolean =>
    sceneLogic.values.activeSceneId === Scene.Insight &&
    insightSceneLogic.findMounted()?.values.insightLogicRef?.logic.key === keyForInsightLogicProps('new')(props)

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
            ['setInsight', 'setInsightMetadata', 'loadInsightSuccess'],
            dataNodeLogic({ key: insightVizDataNodeKey(props) } as DataNodeLogicProps),
            ['loadData', 'loadDataSuccess', 'loadDataFailure', 'setResponse as setInsightData'],
            insightsModel,
            ['renameInsightSuccess'],
        ],
        logic: [insightDataTimingLogic(props), insightUsageLogic(props)],
    })),

    actions({
        setQuery: (query: Node | null) => ({ query }),
        syncQueryFromProps: (query: Node | null) => ({ query }),
        toggleQueryEditorPanel: true,
        toggleDebugPanel: true,
        cancelChanges: true,
        persistDisplayOptions: (query: Node) => ({ query }),
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
                    // Source kinds without a product analytics default (e.g. a TracesQuery from an
                    // AI-generated link) have no default to compare against, so treat as changed
                    if (!(query.source.kind in nodeKindToInsightType)) {
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
        persistDisplayOptions: async ({ query }, breakpoint) => {
            // Never auto-persist while the user is editing this insight in the insight scene.
            // insightDataLogic is keyed `${shortId}/on-dashboard-${dashboardId}`, so an insight
            // opened from a dashboard shares its instance with the dashboard tile — which wired
            // props.setQuery to persistDisplayOptions. Without this guard, any edit in the scene
            // (a display toggle or removing a filter) would PATCH the insight before the user
            // clicks Save. Edits there must persist only through an explicit save.
            if (isInsightSceneInstance(props)) {
                return
            }
            // Debounce rapid clicks. insightDataLogic is keyed per insight, so breakpoint
            // only cancels concurrent saves for THIS insight — not unrelated tiles.
            await breakpoint(700)
            const insightId = values.insight.id
            if (!insightId) {
                return
            }
            // Only persist when the query actually differs from what's saved. The setQuery →
            // props.setQuery path fires for any InsightVizNode change, including programmatic
            // re-syncs (tile re-renders, results refreshes) that carry an unchanged query —
            // persisting those produces spurious saves and activity-log churn.
            if (objectsEqual(query, values.savedInsight.query)) {
                return
            }
            try {
                const updatedItem = await insightsApi.update(insightId, { query })
                // Drop the response if a newer save started while this request was in flight.
                await breakpoint(0)
                actions.renameInsightSuccess(updatedItem)
                lemonToast.success('Insight updated')
            } catch (e) {
                if (!isBreakpoint(e as Error)) {
                    lemonToast.error('Failed to update insight')
                }
            }
        },

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
        loadInsightSuccess: ({ insight }) => {
            // `internalQuery` wins over `insight.query` in the `query` selector, and the SQL editor
            // updates a different logic instance — so a reload alone leaves this scene on the stale
            // query until a hard refresh. Re-sync the override to the freshly loaded query.
            if (insight.query && !objectsEqual(insight.query, values.query)) {
                actions.syncQueryFromProps(insight.query)
            }
        },
        cancelChanges: () => {
            const savedQuery = values.savedInsight.query
            const savedResult = values.savedInsight.result
            actions.setQuery(savedQuery || null)
            actions.setInsightData({ ...values.insightData, result: savedResult ? savedResult : null })
        },
        setQuery: ({ query }) => {
            // When this is the insight scene's own insight, sync the query to the URL
            if (isInsightSceneInstance(props)) {
                const insightId = insightSceneLogic.findMounted()?.values.insightId
                const { pathname, searchParams, hashParams } = router.values.currentLocation
                if (query && (values.queryChanged || insightId === 'new')) {
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
            if (isInsightSceneInstance(props)) {
                const insightId = insightSceneLogic.findMounted()?.values.insightId
                if (insightId && insightId !== 'new') {
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
        // On dashboard tiles props.setQuery persists edits, and `setQuery` is shared with
        // insightVizDataLogic whose listener calls props.setQuery — so re-syncing a stale incoming
        // cached query (e.g. from a tile results refresh) via setQuery loops back and PATCHes it,
        // reverting a just-saved display option. syncQueryFromProps updates local state without the
        // loop. The insight scene keeps setQuery for its URL/draft sync.
        const syncCachedQuery = props.dashboardId != null ? actions.syncQueryFromProps : actions.setQuery
        try {
            if (!objectsEqual(props.cachedInsight.query, values.query)) {
                syncCachedQuery(props.cachedInsight.query)
            }
        } catch {
            // values.query can throw if the logic's state isn't in the store yet
            // (e.g. when InsightCard rebuilds the logic during navigation)
            syncCachedQuery(props.cachedInsight.query)
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
            if (isInsightSceneInstance(props)) {
                const { pathname, searchParams, hashParams } = router.values.currentLocation
                const { q: _, ...hash } = hashParams
                return [pathname, searchParams, hash]
            }
        },
    })),
])
