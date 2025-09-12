import { BuiltLogic, actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'
import { beforeUnload, router } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'
import { objectsEqual } from 'kea-test-utils'

import api from 'lib/api'
import { AlertType } from 'lib/components/Alerts/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { isEmptyObject, isObject } from 'lib/utils'
import { InsightEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { getDefaultQuery } from '~/queries/nodes/InsightViz/utils'
import { DashboardFilter, HogQLVariable, Node } from '~/queries/schema/schema-general'
import { checkLatestVersionsOnQuery } from '~/queries/utils'
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
} from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { insightDataLogicType } from './insightDataLogicType'
import type { insightSceneLogicType } from './insightSceneLogicType'
import { parseDraftQueryFromLocalStorage, parseDraftQueryFromURL } from './utils'

const NEW_INSIGHT = 'new' as const
export type InsightId = InsightShortId | typeof NEW_INSIGHT | null

export interface InsightSceneLogicProps {
    tabId?: string
}

function isDashboardFilterEmpty(filter: DashboardFilter | null): boolean {
    return (
        !filter ||
        (filter.date_from == null &&
            filter.date_to == null &&
            (filter.properties == null || (Array.isArray(filter.properties) && filter.properties.length === 0)) &&
            filter.breakdown_filter == null)
    )
}

export const insightSceneLogic = kea<insightSceneLogicType>([
    path(['scenes', 'insights', 'insightSceneLogic']),
    tabAwareScene(),
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
        ],
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
                setSceneState: (_, { itemId }) =>
                    itemId !== undefined
                        ? itemId === 'new' || itemId?.startsWith('new-')
                            ? 'new'
                            : Number.isInteger(+itemId)
                              ? parseInt(itemId, 10)
                              : itemId
                        : null,
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
        tabId: [() => [(_, props: InsightSceneLogicProps) => props.tabId], (tabId) => tabId],
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
            (s) => [
                s.insightLogicRef,
                s.insight,
                s.dashboardId,
                s.dashboardName,
                s.featureFlags,
                (_, props: InsightSceneLogicProps) => props.tabId,
                s.sceneSource,
            ],
            (insightLogicRef, insight, dashboardId, dashboardName, featureFlags, tabId, sceneSource): Breadcrumb[] => {
                const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]
                return [
                    ...(dashboardId !== null && dashboardName
                        ? [
                              {
                                  key: Scene.Dashboards,
                                  name: 'Dashboards',
                                  path: urls.dashboards(),
                              },
                              {
                                  key: Scene.Dashboard,
                                  name: dashboardName,
                                  path: urls.dashboard(dashboardId),
                              },
                          ]
                        : [
                              sceneSource === 'web-analytics'
                                  ? {
                                        key: Scene.WebAnalytics,
                                        name: 'Web analytics',
                                        path: urls.webAnalytics(),
                                    }
                                  : sceneSource === 'llm-analytics'
                                    ? {
                                          key: 'LLMAnalytics',
                                          name: 'LLM analytics',
                                          path: urls.llmAnalyticsDashboard(),
                                      }
                                    : {
                                          key: Scene.SavedInsights,
                                          name: 'Product analytics',
                                          path: urls.savedInsights(),
                                      },
                          ]),
                    {
                        key: [Scene.Insight, insight?.short_id || `new-${tabId}`],
                        name: insightLogicRef?.logic.values.insightName,
                        onRename:
                            insightLogicRef?.logic.values.canEditInsight && !newSceneLayout
                                ? async (name: string) => {
                                      await insightLogicRef?.logic.asyncActions.setInsightMetadata({ name })
                                  }
                                : undefined,
                        forceEditMode: insightLogicRef?.logic.values.canEditInsight,
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
                return insight?.id
                    ? {
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
                    : null
            },
        ],
        maxContext: [
            (s) => [s.insight, s.filtersOverride, s.variablesOverride],
            (insight: Partial<QueryBasedInsightModel>, filtersOverride, variablesOverride): MaxContextInput[] => {
                if (!insight || !insight.short_id || !insight.query) {
                    return []
                }
                return [
                    createMaxContextHelpers.insight(
                        insight,
                        filtersOverride ?? undefined,
                        variablesOverride ?? undefined
                    ),
                ]
            },
        ],
        hasOverrides: [
            (s) => [s.filtersOverride, s.variablesOverride],
            (filtersOverride, variablesOverride) =>
                (isObject(filtersOverride) && !isEmptyObject(filtersOverride)) ||
                (isObject(variablesOverride) && !isEmptyObject(variablesOverride)),
        ],
    }),
    sharedListeners(({ actions, values }) => ({
        reloadInsightLogic: () => {
            const logicInsightId = values.insight?.short_id ?? null
            const insightId = values.insightId ?? null

            if (logicInsightId !== insightId) {
                const oldRef = values.insightLogicRef // free old logic after mounting new one
                const oldRef2 = values.insightDataLogicRef // free old logic after mounting new one
                if (insightId) {
                    const insightProps: InsightLogicProps = {
                        dashboardItemId: insightId,
                        filtersOverride: values.filtersOverride,
                        variablesOverride: values.variablesOverride,
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
                    values.variablesOverride
                )
            }
        },
    })),
    listeners(({ sharedListeners, values }) => ({
        setInsightMode: sharedListeners.reloadInsightLogic,
        setSceneState: sharedListeners.reloadInsightLogic,
        upgradeQuery: async ({ query }) => {
            let upgradedQuery: Node | null = null

            if (!checkLatestVersionsOnQuery(query)) {
                const response = await api.schema.queryUpgrade({ query })
                upgradedQuery = response.query
            } else {
                upgradedQuery = query
            }

            values.insightLogicRef?.logic.actions.setInsight(
                {
                    ...createEmptyInsight(`new-${values.tabId}`),
                    ...(values.dashboardId ? { dashboards: [values.dashboardId] } : {}),
                    query: upgradedQuery,
                },
                {
                    fromPersistentApi: false,
                    overrideQuery: true,
                }
            )
        },
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        '/insights/:shortId(/:mode)(/:itemId)': (
            { shortId, mode, itemId }, // url params
            { dashboard, alert_id, ...searchParams }, // search params
            { insight: insightType, q, sceneSource }, // hash params
            { method, initial }, // "location changed" event payload
            { searchParams: previousSearchParams } // previous location
        ) => {
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
                insightId = `new-${values.tabId}` as InsightShortId
            }

            const currentScene = sceneLogic.findMounted()?.values

            const alertChanged = alert_id !== values.alertId

            if (
                currentScene?.activeSceneId === Scene.Insight &&
                currentScene.activeSceneLogic &&
                (currentScene.activeSceneLogic as BuiltLogic<insightSceneLogicType>).values.insightId === insightId &&
                (currentScene.activeSceneLogic as BuiltLogic<insightSceneLogicType>).values.insightMode ===
                    insightMode &&
                !alertChanged
            ) {
                // If nothing about the scene has changed, don't do anything
                return
            }

            if (previousSearchParams['event-correlation_page'] !== searchParams['event-correlation_page']) {
                // If a lemon table pagination param has changed, don't do anything
                return
            }

            const dashboardName = dashboardLogic.findMounted({ id: dashboard })?.values.dashboard?.name
            const filtersOverride = searchParams['filters_override']
            const variablesOverride = searchParams['variables_override']

            if (
                insightId !== values.insightId ||
                insightMode !== values.insightMode ||
                itemId !== values.itemId ||
                (sceneSource ?? null) !== values.sceneSource ||
                alertChanged ||
                !objectsEqual(variablesOverride, values.variablesOverride) ||
                !objectsEqual(filtersOverride, values.filtersOverride) ||
                dashboard !== values.dashboardId ||
                dashboardName !== values.dashboardName
            ) {
                actions.setSceneState(
                    insightId,
                    insightMode,
                    itemId,
                    alert_id,
                    // Only pass filters/variables if overrides exist
                    filtersOverride && isDashboardFilterEmpty(filtersOverride) ? undefined : filtersOverride,
                    variablesOverride && !isEmptyObject(variablesOverride) ? variablesOverride : undefined,
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
                    validatingQuery = true
                    if (initial) {
                        actions.upgradeQuery(validQuery)
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
                    values.insightLogicRef?.logic.actions.setInsight(
                        {
                            ...createEmptyInsight(`new-${values.tabId}`),
                            ...(dashboard ? { dashboards: [dashboard] } : {}),
                            query,
                        },
                        {
                            fromPersistentApi: false,
                            overrideQuery: true,
                        }
                    )

                    if (!queryFromUrl) {
                        actions.setFreshQuery(true)
                    }

                    eventUsageLogic.actions.reportInsightCreated(query)
                }
            }
        },
    })),
    tabAwareActionToUrl(({ values }) => {
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
                return [urls.insightNew(), undefined, undefined]
            }

            const baseUrl = insightMode === ItemMode.View ? urls.insightView(insightId) : urls.insightEdit(insightId)
            return [baseUrl, window.location.search, window.location.hash]
        }

        return {
            setInsightId: actionToUrl,
            setInsightMode: actionToUrl,
        }
    }),
    beforeUnload(({ values }) => ({
        enabled: (newLocation?: CombinedLocation) => {
            // Don't run this check on other scenes
            if (values.activeSceneId !== Scene.Insight) {
                return false
            }
            if (values.disableNavigationHooks) {
                return false
            }
            if (values.featureFlags[FEATURE_FLAGS.SCENE_TABS]) {
                return false
            }

            // If just the hash or project part changes, don't show the prompt
            const currentPathname = router.values.currentLocation.pathname.replace(/\/project\/\d+/, '')
            const newPathname = newLocation?.pathname.replace(/\/project\/\d+/, '')
            if (currentPathname === newPathname) {
                return false
            }

            // Don't show the prompt if we're in edit mode (just exploring)
            if (values.insightMode !== ItemMode.Edit) {
                return false
            }

            const metadataChanged = !!values.insightLogicRef?.logic.values.insightChanged
            const queryChanged = !!values.insightDataLogicRef?.logic.values.queryChanged
            const draftQueryFromLocalStorage = localStorage.getItem(`draft-query-${values.currentTeamId}`)
            let draftQuery: { query: Node; timestamp: number } | null = null
            if (draftQueryFromLocalStorage) {
                const parsedQuery = parseDraftQueryFromLocalStorage(draftQueryFromLocalStorage)
                if (parsedQuery) {
                    draftQuery = parsedQuery
                } else {
                    // If the draft query is invalid, remove it
                    localStorage.removeItem(`draft-query-${values.currentTeamId}`)
                }
            }
            const query = values.insightDataLogicRef?.logic.values.query

            if (draftQuery && query && objectsEqual(draftQuery.query, query)) {
                return false
            }

            const isChanged = metadataChanged || queryChanged

            if (!isChanged) {
                return false
            }

            // Do not show confirmation if newPathname is undefined; this usually means back button in browser
            if (newPathname === undefined) {
                const savedQuery = values.insightDataLogicRef?.logic.values.savedInsight.query
                values.insightDataLogicRef?.logic.actions.setQuery(savedQuery || null)
                return false
            }

            return true
        },
        message: 'Leave insight?\nChanges you made will be discarded.',
        onConfirm: () => {
            values.insightDataLogicRef?.logic.actions.cancelChanges()
        },
    })),
])
