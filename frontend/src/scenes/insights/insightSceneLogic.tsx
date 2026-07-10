import { BuiltLogic, actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'
import { urlToAction } from 'kea-router'
import { objectsEqual } from 'kea-test-utils'

import api from 'lib/api'
import { AlertType } from 'lib/components/Alerts/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { InsightEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { isEmptyObject, isObject } from 'lib/utils/guards'
import { isDashboardFilterEmpty } from 'scenes/dashboard/dashboardFilterEmpty'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { getDefaultQuery } from '~/queries/nodes/InsightViz/utils'
import {
    DashboardFilter,
    FileSystemIconType,
    HogQLVariable,
    Node,
    NodeKind,
    QueryLogTags,
    TileFilters,
} from '~/queries/schema/schema-general'
import {
    checkLatestVersionsOnQuery,
    convertDataTableNodeToDataVisualizationNode,
    isDataTableNode,
    isInsightVizNode,
} from '~/queries/utils'
import {
    ActivityScope,
    Breadcrumb,
    DashboardType,
    InsightLogicProps,
    InsightSceneSource,
    InsightShortId,
    InsightType,
    ItemMode,
    ProjectTreeRef,
    QueryBasedInsightModel,
    SidePanelTab,
} from '~/types'

import { PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS } from 'products/product_analytics/frontend/constants'

import { insightDataLogic } from './insightDataLogic'
import { insightDataLogicType } from './insightDataLogicType'
import type { insightSceneLogicType } from './insightSceneLogicType'
import { getInsightIconTypeFromQuery, parseDraftQueryFromURL } from './utils'

const NEW_INSIGHT = 'new' as const
export type InsightId = InsightShortId | typeof NEW_INSIGHT | null

function normalizeItemId(itemId: string | undefined): string | number | null {
    if (itemId === undefined) {
        return null
    }
    if (itemId === 'new' || itemId.startsWith('new-')) {
        return 'new'
    }
    if (Number.isInteger(+itemId)) {
        return parseInt(itemId, 10)
    }
    return itemId
}

// Tag a new insight's query with the product_analytics productKey (on the executed source query) so
// ClickHouse doesn't reject it as untagged. Leaves an existing productKey untouched.
function withDefaultProductAnalyticsTags(query: Node): Node {
    if (isInsightVizNode(query) && !query.source.tags?.productKey) {
        return {
            ...query,
            source: { ...query.source, tags: { ...query.source.tags, ...PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS } },
        } as Node
    }
    // EventsNode is the only DataTableNode source kind without a `tags` field and its schema forbids
    // extra keys, so tagging it would make the payload invalid.
    if (isDataTableNode(query) && query.source.kind !== NodeKind.EventsNode) {
        const source = query.source as { tags?: QueryLogTags | null }
        if (!source.tags?.productKey) {
            return {
                ...query,
                source: { ...query.source, tags: { ...source.tags, ...PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS } },
            } as Node
        }
    }
    return query
}

export const insightSceneLogic = kea<insightSceneLogicType>([
    path(['scenes', 'insights', 'insightSceneLogic']),
    connect(() => ({
        logic: [eventUsageLogic],
        values: [
            teamLogic,
            ['currentTeam', 'currentTeamId'],
            sceneLogic,
            ['activeSceneId'],
            preflightLogic,
            ['disableNavigationHooks'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
            featureFlagLogic,
            ['featureFlags'],
            sceneLayoutLogic,
            ['scenePanelIsPresent'],
        ],
        actions: [sceneLayoutLogic, ['setScenePanelIsPresent']],
    })),
    actions({
        setInsightId: (insightId: InsightShortId) => ({ insightId }),
        setInsightMode: (insightMode: ItemMode, source: InsightEventSource | null) => ({ insightMode, source }),
        setSceneState: (
            insightId: InsightShortId,
            insightMode: ItemMode,
            itemId: string | undefined,
            alertId: AlertType['id'] | undefined,
            filtersOverride: DashboardFilter | undefined,
            variablesOverride: Record<string, HogQLVariable> | undefined,
            tileFiltersOverride: TileFilters | undefined,
            dashboardId: DashboardType['id'] | undefined,
            dashboardName: DashboardType['name'] | undefined,
            sceneSource: InsightSceneSource | null
        ) => ({
            insightId,
            insightMode,
            itemId,
            alertId,
            dashboardId,
            dashboardName,
            filtersOverride,
            variablesOverride,
            tileFiltersOverride,
            sceneSource,
        }),
        setInsightLogicRef: (logic: BuiltLogic<insightLogicType> | null, unmount: null | (() => void)) => ({
            logic,
            unmount,
        }),
        setInsightDataLogicRef: (logic: BuiltLogic<insightDataLogicType> | null, unmount: null | (() => void)) => ({
            logic,
            unmount,
        }),
        setFreshQuery: (freshQuery: boolean) => ({ freshQuery }),
        upgradeQuery: (query: Node) => ({ query }),
    }),
    reducers({
        insightId: [
            null as null | InsightId,
            {
                setSceneState: (_, { insightId }) => insightId,
            },
        ],
        insightMode: [
            ItemMode.View as ItemMode,
            {
                setSceneState: (_, { insightMode }) => insightMode,
            },
        ],
        sceneSource: [
            null as null | InsightSceneSource,
            {
                setSceneState: (_, { sceneSource }) => sceneSource ?? null,
            },
        ],
        itemId: [
            null as null | string | number,
            {
                setSceneState: (_, { itemId }) => normalizeItemId(itemId),
            },
        ],
        alertId: [
            null as null | AlertType['id'],
            {
                setSceneState: (_, { alertId }) => (alertId !== undefined ? alertId : null),
            },
        ],
        dashboardId: [
            null as null | DashboardType['id'],
            {
                setSceneState: (_, { dashboardId }) => (dashboardId !== undefined ? dashboardId : null),
            },
        ],
        dashboardName: [
            null as null | DashboardType['name'],
            {
                setSceneState: (_, { dashboardName }) => (dashboardName !== undefined ? dashboardName : null),
            },
        ],
        filtersOverride: [
            null as null | DashboardFilter,
            {
                setSceneState: (_, { filtersOverride }) => (filtersOverride !== undefined ? filtersOverride : null),
            },
        ],
        variablesOverride: [
            null as null | Record<string, HogQLVariable>,
            {
                setSceneState: (_, { variablesOverride }) =>
                    variablesOverride !== undefined ? variablesOverride : null,
            },
        ],
        tileFiltersOverride: [
            null as null | TileFilters,
            {
                setSceneState: (_, { tileFiltersOverride }) =>
                    tileFiltersOverride !== undefined ? tileFiltersOverride : null,
            },
        ],
        insightLogicRef: [
            null as null | {
                logic: BuiltLogic<insightLogicType>
                unmount: () => void
            },
            {
                setInsightLogicRef: (_, { logic, unmount }) => (logic && unmount ? { logic, unmount } : null),
            },
        ],
        insightDataLogicRef: [
            null as null | {
                logic: BuiltLogic<insightDataLogicType>
                unmount: () => void
            },
            {
                setInsightDataLogicRef: (_, { logic, unmount }) => (logic && unmount ? { logic, unmount } : null),
            },
        ],
        freshQuery: [false, { setFreshQuery: (_, { freshQuery }) => freshQuery }],
    }),
    selectors({
        insightQuerySelector: [
            (s) => [s.insightDataLogicRef],
            (insightDataLogicRef) => insightDataLogicRef?.logic.selectors.query,
        ],
        insightQuery: [
            (s) => [
                (state, props) => {
                    try {
                        return s.insightQuerySelector?.(state, props)?.(state, props)
                    } catch {
                        return null
                    }
                },
            ],
            (insightQuery) => insightQuery,
        ],
        insightDataSelector: [
            (s) => [s.insightDataLogicRef],
            (insightDataLogicRef) => insightDataLogicRef?.logic.selectors.insightData,
        ],
        insightData: [
            (s) => [
                (state, props) => {
                    try {
                        return s.insightDataSelector?.(state, props)?.(state, props)
                    } catch {
                        return null
                    }
                },
            ],
            (insightData) => insightData,
        ],
        insightSelector: [(s) => [s.insightLogicRef], (insightLogicRef) => insightLogicRef?.logic.selectors.insight],
        insight: [
            (s) => [
                (state, props) => {
                    try {
                        return s.insightSelector?.(state, props)?.(state, props)
                    } catch {
                        // Sometimes the insight logic hasn't mounted yet
                        return null
                    }
                },
            ],
            (insight) => insight,
        ],
        breadcrumbs: [
            (s) => [s.insightLogicRef, s.insight, s.insightQuery, s.dashboardId, s.dashboardName, s.sceneSource],
            (insightLogicRef, insight, insightQuery, dashboardId, dashboardName, sceneSource): Breadcrumb[] => {
                const dashboardLabel = dashboardName ?? 'Dashboard'
                return [
                    ...(dashboardId !== null
                        ? [
                              {
                                  key: Scene.Dashboards,
                                  name: 'Dashboards',
                                  path: urls.dashboards(),
                                  iconType: 'dashboard' as FileSystemIconType,
                              },
                              {
                                  key: Scene.Dashboard,
                                  name: dashboardLabel,
                                  path: urls.dashboard(dashboardId),
                                  iconType: 'dashboard' as FileSystemIconType,
                              },
                          ]
                        : [
                              sceneSource === 'web-analytics'
                                  ? {
                                        key: Scene.WebAnalytics,
                                        name: 'Web analytics',
                                        path: urls.webAnalytics(),
                                        iconType: 'web_analytics' as FileSystemIconType,
                                    }
                                  : sceneSource === 'llm-analytics'
                                    ? {
                                          key: 'AIObservability',
                                          name: 'AI observability',
                                          path: urls.aiObservabilityDashboard(),
                                          iconType: 'llm_analytics' as FileSystemIconType,
                                      }
                                    : sceneSource === 'endpoints'
                                      ? {
                                            key: Scene.Endpoints,
                                            name: 'endpoints',
                                            path: urls.endpoints(),
                                            iconType: 'endpoints' as FileSystemIconType,
                                        }
                                      : {
                                            key: Scene.SavedInsights,
                                            name: 'Product analytics',
                                            path: urls.savedInsights(),
                                            iconType: 'product_analytics' as FileSystemIconType,
                                        },
                          ]),
                    {
                        key: [Scene.Insight, insight?.short_id || 'new'],
                        name: insightLogicRef?.logic.values.insightName,
                        forceEditMode: insightLogicRef?.logic.values.canEditInsight,
                        iconType: getInsightIconTypeFromQuery(insightQuery),
                    },
                ]
            },
        ],
        projectTreeRef: [
            (s) => [s.insightId],
            (insightId): ProjectTreeRef => ({
                type: 'insight',
                ref: insightId && insightId !== 'new' && !insightId.startsWith('new-') ? String(insightId) : null,
            }),
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.insight],
            (insight): SidePanelSceneContext | null => {
                if (!insight?.id) {
                    // An unsaved insight has no numeric id yet. Still declare the Insight scope so
                    // sidePanelContextLogic does not fall back to the URL-based guesser (which would
                    // drop the missing item_id and list every Insight-scoped comment in the team),
                    // but mark discussions disabled until the insight is saved.
                    return {
                        activity_scope: ActivityScope.INSIGHT,
                        discussions_disabled: true,
                    }
                }
                return {
                    activity_scope: ActivityScope.INSIGHT,
                    activity_item_id: `${insight.id}`,
                    // when e.g. constructing URLs for an insight we don't use the id,
                    // so we also store the short id
                    activity_item_context: {
                        short_id: `${insight.short_id}`,
                    },
                    access_control_resource: 'insight',
                    access_control_resource_id: `${insight.id}`,
                }
            },
        ],
        maxContext: [
            (s) => [s.insight, s.filtersOverride, s.variablesOverride],
            (insight: Partial<QueryBasedInsightModel>, filtersOverride, variablesOverride): MaxContextInput[] => {
                if (!insight || !insight.short_id || !insight.query) {
                    return []
                }
                return [
                    createMaxContextHelpers.insight(insight, {
                        filtersOverride: filtersOverride ?? undefined,
                        variablesOverride: variablesOverride ?? undefined,
                    }),
                ]
            },
        ],
        hasOverrides: [
            (s) => [s.filtersOverride, s.variablesOverride, s.tileFiltersOverride],
            (filtersOverride, variablesOverride, tileFiltersOverride) =>
                !isDashboardFilterEmpty(filtersOverride) ||
                (isObject(variablesOverride) && !isEmptyObject(variablesOverride)) ||
                !isDashboardFilterEmpty(tileFiltersOverride),
        ],
    }),
    sharedListeners(({ actions, values }) => ({
        /**
         * The editor must show the insight in the URL and the tile the user opened—not a different saved insight.
         * After "Save as" from a dashboard, the tile still belongs to the original; if we kept the wrong editor
         * state, going back and editing that tile could show the copy instead. Remount when those disagree, and
         * when the URL insight does not match which insight this editor was opened from.
         */
        reloadInsightLogic: () => {
            const logicInsightId = values.insight?.short_id ?? null
            const insightId = values.insightId ?? null
            const mountedDashboardItemId = values.insightLogicRef?.logic.props.dashboardItemId ?? null
            const propsMismatch = Boolean(insightId && mountedDashboardItemId && mountedDashboardItemId !== insightId)

            if (logicInsightId !== insightId || propsMismatch) {
                const oldRef = values.insightLogicRef // free old logic after mounting new one
                const oldRef2 = values.insightDataLogicRef // free old logic after mounting new one
                if (insightId) {
                    const insightProps: InsightLogicProps = {
                        dashboardItemId: insightId,
                        dashboardId: values.dashboardId ?? undefined,
                        filtersOverride: values.filtersOverride,
                        variablesOverride: values.variablesOverride,
                        tileFiltersOverride: values.tileFiltersOverride,
                    }

                    const logic = insightLogic.build(insightProps)
                    const unmount = logic.mount()
                    actions.setInsightLogicRef(logic, unmount)

                    const logic2 = insightDataLogic.build(insightProps)
                    const unmount2 = logic2.mount()
                    actions.setInsightDataLogicRef(logic2, unmount2)
                } else {
                    actions.setInsightLogicRef(null, null)
                    actions.setInsightDataLogicRef(null, null)
                }
                if (oldRef) {
                    oldRef.unmount()
                }
                if (oldRef2) {
                    oldRef2.unmount()
                }
            } else if (insightId) {
                values.insightLogicRef?.logic.actions.loadInsight(
                    insightId as InsightShortId,
                    values.filtersOverride,
                    values.variablesOverride,
                    values.tileFiltersOverride
                )
            }
        },
    })),
    listeners(({ sharedListeners, values }) => ({
        setInsightMode: sharedListeners.reloadInsightLogic,
        setSceneState: [
            sharedListeners.reloadInsightLogic,
            ({ sceneSource }) => {
                // Only open here when the scene panel already exists; otherwise Info isn't in
                // `enabledTabs` yet and SidePanel's fallback reroutes to Max. The fresh-navigation
                // case is handled by the `setScenePanelIsPresent` listener below.
                if (sceneSource === 'endpoints' && values.scenePanelIsPresent) {
                    sidePanelStateLogic.findMounted()?.actions.openSidePanel(SidePanelTab.Info)
                }
            },
        ],
        setScenePanelIsPresent: ({ active }) => {
            if (active && values.sceneSource === 'endpoints') {
                sidePanelStateLogic.findMounted()?.actions.openSidePanel(SidePanelTab.Info)
            }
        },
        upgradeQuery: async ({ query }) => {
            let upgradedQuery: Node | null = null

            if (!checkLatestVersionsOnQuery(query)) {
                const response = await api.schema.queryUpgrade({ query })
                upgradedQuery = response.query
            } else {
                upgradedQuery = query
            }

            upgradedQuery = convertDataTableNodeToDataVisualizationNode(upgradedQuery)

            if (values.insightId === 'new' || values.insightId?.startsWith('new-')) {
                values.insightLogicRef?.logic.actions.setInsight(
                    {
                        ...createEmptyInsight('new'),
                        ...(values.dashboardId ? { dashboards: [values.dashboardId] } : {}),
                        query: upgradedQuery ? withDefaultProductAnalyticsTags(upgradedQuery) : upgradedQuery,
                    },
                    {
                        fromPersistentApi: false,
                        overrideQuery: true,
                    }
                )
            } else {
                values.insightDataLogicRef?.logic.actions.setQuery(upgradedQuery)
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/insights/:shortId(/:mode)(/:itemId)': (
            { shortId, mode, itemId }, // url params
            { dashboard, alert_id, ...searchParams }, // search params
            { insight: insightType, q, sceneSource }, // hash params
            { method, initial }, // "location changed" event payload
            { searchParams: previousSearchParams } // previous location
        ) => {
            // `/insights/quick-start` is handled by Scene.InsightQuickStart, not the Insight scene.
            // The :shortId pattern greedily matches it, so bail out before triggering a loadInsight
            // for a non-existent short_id.
            if (shortId === 'quick-start') {
                return
            }
            const insightMode =
                mode === 'subscriptions'
                    ? ItemMode.Subscriptions
                    : mode === 'alerts'
                      ? ItemMode.Alerts
                      : mode === 'sharing'
                        ? ItemMode.Sharing
                        : mode === 'edit' || shortId === 'new'
                          ? ItemMode.Edit
                          : ItemMode.View
            let insightId = String(shortId) as InsightShortId
            if (insightId === 'new') {
                insightId = 'new' as InsightShortId
            }

            const currentScene = sceneLogic.findMounted()?.values

            const alertChanged = (alert_id ?? null) !== values.alertId
            const isExistingInsight = shortId !== 'new'

            // `activeSceneLogic` can unmount mid-transition (e.g. navigating dashboard ↔ insight edit).
            // Reading `.values` on an unmounted logic throws `[KEA] Can not find path`, so only read it
            // while it's still mounted — otherwise treat the scene as changed and re-process below.
            const activeSceneLogic = currentScene?.activeSceneLogic as BuiltLogic<insightSceneLogicType> | undefined
            const activeSceneValues = activeSceneLogic?.isMounted() ? activeSceneLogic.values : undefined

            const itemIdChanged = activeSceneValues?.itemId !== normalizeItemId(itemId)

            if (
                isExistingInsight &&
                method !== 'PUSH' &&
                currentScene?.activeSceneId === Scene.Insight &&
                activeSceneValues &&
                activeSceneValues.insightId === insightId &&
                activeSceneValues.insightMode === insightMode &&
                !alertChanged &&
                !itemIdChanged
            ) {
                // Nothing about the scene has changed, skip re-processing.
                // New insights (/insights/new) are excluded because the insight type
                // or dashboard in hash/search params may have changed.
                // PUSH navigations are excluded because the user explicitly navigated
                // (e.g. clicking an insight link from the list), so we must reload.
                return
            }

            if (previousSearchParams['event-correlation_page'] !== searchParams['event-correlation_page']) {
                // If a lemon table pagination param has changed, don't do anything
                return
            }

            const dashboardName = dashboardLogic.findMounted({ id: dashboard })?.values.dashboard?.name
            const filtersOverride = searchParams['filters_override']
            const variablesOverride = searchParams['variables_override']
            const tileFiltersOverride = searchParams['tile_filters_override']

            if (
                initial ||
                method === 'PUSH' ||
                insightId !== values.insightId ||
                insightMode !== values.insightMode ||
                (itemId ?? null) !== values.itemId ||
                (sceneSource ?? null) !== values.sceneSource ||
                alertChanged ||
                !objectsEqual(variablesOverride ?? null, values.variablesOverride) ||
                !objectsEqual(filtersOverride ?? null, values.filtersOverride) ||
                !objectsEqual(tileFiltersOverride ?? null, values.tileFiltersOverride) ||
                (dashboard ?? null) !== values.dashboardId ||
                (dashboardName ?? null) !== values.dashboardName
            ) {
                actions.setSceneState(
                    insightId,
                    insightMode,
                    itemId,
                    alert_id,
                    // Only pass filters/variables if overrides exist
                    filtersOverride && isDashboardFilterEmpty(filtersOverride) ? undefined : filtersOverride,
                    variablesOverride && !isEmptyObject(variablesOverride) ? variablesOverride : undefined,
                    tileFiltersOverride && isDashboardFilterEmpty(tileFiltersOverride)
                        ? undefined
                        : tileFiltersOverride,
                    dashboard,
                    dashboardName,
                    sceneSource
                )
            }

            let queryFromUrl: Node | null = null
            let validatingQuery = false
            if (q) {
                const validQuery = typeof q === 'string' ? parseDraftQueryFromURL(q) : q
                if (validQuery) {
                    if (initial) {
                        validatingQuery = true
                        actions.upgradeQuery(validQuery)
                    } else if (method !== 'REPLACE') {
                        queryFromUrl = validQuery
                    }
                } else {
                    console.error('Invalid query', q)
                }
            } else if (insightType && Object.values(InsightType).includes(insightType)) {
                queryFromUrl = getDefaultQuery(insightType, values.filterTestAccountsDefault)
            }

            actions.setFreshQuery(false)
            // reset the insight's state if we have to
            if ((initial || queryFromUrl || method === 'PUSH') && !validatingQuery) {
                if (insightId === 'new' || insightId.startsWith('new-')) {
                    const query = queryFromUrl || getDefaultQuery(InsightType.TRENDS, values.filterTestAccountsDefault)
                    const taggedQuery = withDefaultProductAnalyticsTags(query)
                    values.insightLogicRef?.logic.actions.setInsight(
                        {
                            ...createEmptyInsight('new'),
                            ...(dashboard ? { dashboards: [dashboard] } : {}),
                            query: taggedQuery,
                        },
                        {
                            fromPersistentApi: false,
                            overrideQuery: true,
                        }
                    )

                    if (!queryFromUrl) {
                        actions.setFreshQuery(true)
                    }

                    eventUsageLogic.actions.reportInsightStarted(query)
                }
            }
        },
    })),
    trackedActionToUrl(({ values }) => {
        // Use the browser redirect to determine state to hook into beforeunload prevention
        const actionToUrl = ({
            insightMode = values.insightMode,
            insightId = values.insightId,
        }: {
            insightMode?: ItemMode
            insightId?: InsightShortId | 'new' | null
        }):
            | [string, Record<string, any> | string | undefined, Record<string, any> | string | undefined]
            | undefined => {
            if (!insightId || insightId === 'new' || insightId.startsWith('new-')) {
                // Preserve search + hash (e.g. the `#q=` query) so post-load URL sync doesn't strip the drill-down query
                return [urls.insightNew(), window.location.search, window.location.hash]
            }

            const baseUrl = insightMode === ItemMode.View ? urls.insightView(insightId) : urls.insightEdit(insightId)
            return [baseUrl, window.location.search, window.location.hash]
        }

        return {
            setInsightId: actionToUrl,
            setInsightMode: actionToUrl,
        }
    }),
])
