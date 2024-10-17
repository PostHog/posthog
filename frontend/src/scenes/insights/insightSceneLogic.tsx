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

import { ActivityFilters } from '~/layout/navigation-3000/sidepanel/panels/activity/activityForSceneLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { getDefaultQuery } from '~/queries/nodes/InsightViz/utils'
import { DashboardFilter, HogQLVariable, Node } from '~/queries/schema'
import { ActivityScope, Breadcrumb, DashboardType, InsightShortId, InsightType, ItemMode } from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { insightDataLogicType } from './insightDataLogicType'
import type { insightSceneLogicType } from './insightSceneLogicType'
import { summarizeInsight } from './summarizeInsight'

export const insightSceneLogic = kea<insightSceneLogicType>([
    path(['scenes', 'insights', 'insightSceneLogic']),
    connect(() => ({
        logic: [eventUsageLogic],
        values: [
            teamLogic,
            ['currentTeam'],
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
    }),
    reducers({
        insightId: [
            null as null | 'new' | InsightShortId,
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
                        onRename: async (name: string) => {
                            await insightLogicRef?.logic.asyncActions.setInsightMetadata({ name })
                        },
                    },
                ]
            },
        ],
        activityFilters: [
            (s) => [s.insight],
            (insight): ActivityFilters | null => {
                return insight
                    ? {
                          scope: ActivityScope.INSIGHT,
                          item_id: `${insight.id}`,
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
                queryFromUrl = JSON.parse(q)
            } else if (insightType && Object.values(InsightType).includes(insightType)) {
                queryFromUrl = getDefaultQuery(insightType, values.filterTestAccountsDefault)
            }

            // Redirect to a simple URL if we had a query in the URL
            if (q || insightType) {
                router.actions.replace(
                    insightId === 'new'
                        ? urls.insightNew(undefined, dashboard)
                        : insightMode === ItemMode.Edit
                        ? urls.insightEdit(insightId)
                        : urls.insightView(insightId)
                )
            }

            // reset the insight's state if we have to
            if (initial || method === 'PUSH' || queryFromUrl) {
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
        }): string | undefined =>
            insightId && insightId !== 'new'
                ? insightMode === ItemMode.View
                    ? urls.insightView(insightId)
                    : urls.insightEdit(insightId)
                : undefined

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

            return metadataChanged || queryChanged
        },
        message: 'Leave insight?\nChanges you made will be discarded.',
        onConfirm: () => {
            values.insightDataLogicRef?.logic.actions.cancelChanges()
        },
    })),
])
