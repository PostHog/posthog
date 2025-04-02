import { actions, BuiltLogic, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'
import { actionToUrl, beforeUnload, router, urlToAction } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'
import { objectsEqual } from 'kea-test-utils'
import { AlertType } from 'lib/components/Alerts/types'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { getDefaultQuery } from '~/queries/nodes/InsightViz/utils'
import { DashboardFilter, HogQLVariable, Node } from '~/queries/schema/schema-general'
import {
    ActivityScope,
    Breadcrumb,
    DashboardType,
    InsightShortId,
    InsightType,
    ItemMode,
    ProjectTreeRef,
} from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { insightDataLogicType } from './insightDataLogicType'
import type { insightSceneLogicType } from './insightSceneLogicType'
import { summarizeInsight } from './summarizeInsight'
import { parseDraftQueryFromLocalStorage, parseDraftQueryFromURL } from './utils'

const NEW_INSIGHT = 'new' as const
export type InsightId = InsightShortId | typeof NEW_INSIGHT | null

export const insightSceneLogic = kea<insightSceneLogicType>([
    path(['scenes', 'insights', 'insightSceneLogic']),
    connect(() => ({
        logic: [eventUsageLogic],
        values: [
            teamLogic,
            ['currentTeam', 'currentTeamId'],
            sceneLogic,
            ['activeScene'],
            preflightLogic,
            ['disableNavigationHooks'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
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
            dashboardName: DashboardType['name'] | undefined
        ) => ({
            insightId,
            insightMode,
            itemId,
            alertId,
            dashboardId,
            dashboardName,
            filtersOverride,
            variablesOverride,
        }),
        setInsightLogicRef: (logic: BuiltLogic<insightLogicType> | null, unmount: null | (() => void)) => ({
            logic,
            unmount,
        }),
        setInsightDataLogicRef: (logic: BuiltLogic<insightDataLogicType> | null, unmount: null | (() => void)) => ({
            logic,
            unmount,
        }),
        setOpenedWithQuery: (query: Node | null) => ({ query }),
        setFreshQuery: (freshQuery: boolean) => ({ freshQuery }),
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
        itemId: [
            null as null | string | number,
            {
                setSceneState: (_, { itemId }) =>
                    itemId !== undefined
                        ? itemId === 'new'
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
        openedWithQuery: [null as Node | null, { setOpenedWithQuery: (_, { query }) => query }],
        freshQuery: [false, { setFreshQuery: (_, { freshQuery }) => freshQuery }],
    }),
    selectors(() => ({
        insightSelector: [(s) => [s.insightLogicRef], (insightLogicRef) => insightLogicRef?.logic.selectors.insight],
        insight: [(s) => [(state, props) => s.insightSelector?.(state, props)?.(state, props)], (insight) => insight],
        breadcrumbs: [
            (s) => [
                s.insightLogicRef,
                s.insight,
                s.dashboardId,
                s.dashboardName,
                groupsModel.selectors.aggregationLabel,
                cohortsModel.selectors.cohortsById,
                mathsLogic.selectors.mathDefinitions,
            ],
            (
                insightLogicRef,
                insight,
                dashboardId,
                dashboardName,
                aggregationLabel,
                cohortsById,
                mathDefinitions
            ): Breadcrumb[] => {
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
                              {
                                  key: Scene.SavedInsights,
                                  name: 'Product analytics',
                                  path: urls.savedInsights(),
                              },
                          ]),
                    {
                        key: [Scene.Insight, insight?.short_id || 'new'],
                        name:
                            insight?.name ||
                            summarizeInsight(insight?.query, {
                                aggregationLabel,
                                cohortsById,
                                mathDefinitions,
                            }),
                        onRename: insightLogicRef?.logic.values.canEditInsight
                            ? async (name: string) => {
                                  await insightLogicRef?.logic.asyncActions.setInsightMetadata({ name })
                              }
                            : undefined,
                    },
                ]
            },
        ],
        projectTreeRef: [
            (s) => [s.insightId],
            (insightId): ProjectTreeRef => ({ type: 'insight', ref: String(insightId) }),
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.insight],
            (insight): SidePanelSceneContext | null => {
                return insight?.id
                    ? {
                          activity_scope: ActivityScope.INSIGHT,
                          activity_item_id: `${insight.id}`,
                          access_control_resource: 'insight',
                          access_control_resource_id: `${insight.id}`,
                      }
                    : null
            },
        ],
    })),
    sharedListeners(({ actions, values }) => ({
        reloadInsightLogic: () => {
            const logicInsightId = values.insight?.short_id ?? null
            const insightId = values.insightId ?? null

            if (logicInsightId !== insightId) {
                const oldRef = values.insightLogicRef // free old logic after mounting new one
                const oldRef2 = values.insightDataLogicRef // free old logic after mounting new one
                if (insightId) {
                    const insightProps = {
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
    listeners(({ sharedListeners }) => ({
        setInsightMode: sharedListeners.reloadInsightLogic,
        setSceneState: sharedListeners.reloadInsightLogic,
    })),
    urlToAction(({ actions, values }) => ({
        '/insights/:shortId(/:mode)(/:itemId)': (
            { shortId, mode, itemId }, // url params
            { dashboard, alert_id, ...searchParams }, // search params
            { insight: insightType, q }, // hash params
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
            const insightId = String(shortId) as InsightShortId

            const currentScene = sceneLogic.findMounted()?.values

            if (
                currentScene?.activeScene === Scene.Insight &&
                currentScene.activeSceneLogic?.values.insightId === insightId &&
                currentScene.activeSceneLogic?.values.mode === insightMode
            ) {
                // If nothing about the scene has changed, don't do anything
                return
            }

            if (previousSearchParams['event-correlation_page'] !== searchParams['event-correlation_page']) {
                // If a lemon table pagination param has changed, don't do anything
                return
            }

            const dashboardName = dashboardLogic.findMounted({ id: dashboard })?.values.dashboard?.name
            const filtersOverride = dashboardLogic.findMounted({ id: dashboard })?.values.temporaryFilters

            if (
                insightId !== values.insightId ||
                insightMode !== values.insightMode ||
                itemId !== values.itemId ||
                alert_id !== values.alertId ||
                !objectsEqual(searchParams['variables_override'], values.variablesOverride) ||
                !objectsEqual(filtersOverride, values.filtersOverride) ||
                dashboard !== values.dashboardId ||
                dashboardName !== values.dashboardName
            ) {
                actions.setSceneState(
                    insightId,
                    insightMode,
                    itemId,
                    alert_id,
                    filtersOverride,
                    searchParams['variables_override'],
                    dashboard,
                    dashboardName
                )
            }

            let queryFromUrl: Node | null = null
            if (q) {
                const validQuery = parseDraftQueryFromURL(q)
                if (validQuery) {
                    queryFromUrl = validQuery
                } else {
                    console.error('Invalid query', q)
                }
            } else if (insightType && Object.values(InsightType).includes(insightType)) {
                queryFromUrl = getDefaultQuery(insightType, values.filterTestAccountsDefault)
            }

            actions.setFreshQuery(false)

            // reset the insight's state if we have to
            if (initial || queryFromUrl || method === 'PUSH') {
                if (insightId === 'new') {
                    const query = queryFromUrl || getDefaultQuery(InsightType.TRENDS, values.filterTestAccountsDefault)
                    values.insightLogicRef?.logic.actions.setInsight(
                        {
                            ...createEmptyInsight('new'),
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

                    actions.setOpenedWithQuery(query)

                    eventUsageLogic.actions.reportInsightCreated(query)
                }
            }
        },
    })),
    actionToUrl(({ values }) => {
        // Use the browser redirect to determine state to hook into beforeunload prevention
        const actionToUrl = ({
            insightMode = values.insightMode,
            insightId = values.insightId,
        }: {
            insightMode?: ItemMode
            insightId?: InsightShortId | 'new' | null
        }): string | undefined => {
            if (!insightId || insightId === 'new') {
                return undefined
            }

            const baseUrl = insightMode === ItemMode.View ? urls.insightView(insightId) : urls.insightEdit(insightId)
            const searchParams = window.location.search
            return searchParams ? `${baseUrl}${searchParams}` : baseUrl
        }

        return {
            setInsightId: actionToUrl,
            setInsightMode: actionToUrl,
        }
    }),
    beforeUnload(({ values }) => ({
        enabled: (newLocation?: CombinedLocation) => {
            // Don't run this check on other scenes
            if (values.activeScene !== Scene.Insight) {
                return false
            }

            if (values.disableNavigationHooks) {
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

            return metadataChanged || queryChanged
        },
        message: 'Leave insight?\nChanges you made will be discarded.',
        onConfirm: () => {
            values.insightDataLogicRef?.logic.actions.cancelChanges()
        },
    })),
])
