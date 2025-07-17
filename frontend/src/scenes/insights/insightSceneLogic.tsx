import { actions, BuiltLogic, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { objectsEqual } from 'kea-test-utils'
import { AlertType } from 'lib/components/Alerts/types'
import { isEmptyObject } from 'lib/utils'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
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
    QueryBasedInsightModel,
} from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { insightDataLogicType } from './insightDataLogicType'
import type { insightSceneLogicType } from './insightSceneLogicType'
import { parseDraftQueryFromURL } from './utils'
import api from 'lib/api'
import { checkLatestVersionsOnQuery } from '~/queries/utils'

import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'

const NEW_INSIGHT = 'new' as const
export type InsightId = InsightShortId | typeof NEW_INSIGHT | null

export function isDashboardFilterEmpty(filter: DashboardFilter | null): boolean {
    return (
        !filter ||
        (filter.date_from === null &&
            filter.date_to === null &&
            (filter.properties === null || (Array.isArray(filter.properties) && filter.properties.length === 0)) &&
            filter.breakdown_filter === null)
    )
}

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
        freshQuery: [false, { setFreshQuery: (_, { freshQuery }) => freshQuery }],
    }),
    selectors(() => ({
        insightSelector: [(s) => [s.insightLogicRef], (insightLogicRef) => insightLogicRef?.logic.selectors.insight],
        insight: [(s) => [(state, props) => s.insightSelector?.(state, props)?.(state, props)], (insight) => insight],
        breadcrumbs: [
            (s) => [s.insightLogicRef, s.insight, s.dashboardId, s.dashboardName],
            (insightLogicRef, insight, dashboardId, dashboardName): Breadcrumb[] => {
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
                        name: insightLogicRef?.logic.values.insightName,
                        onRename: insightLogicRef?.logic.values.canEditInsight
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
                ref: insightId && insightId !== 'new' ? String(insightId) : null,
            }),
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
        maxContext: [
            (s) => [s.insight],
            (insight: Partial<QueryBasedInsightModel>): MaxContextInput[] => {
                if (!insight || !insight.short_id || !insight.query) {
                    return []
                }
                return [createMaxContextHelpers.insight(insight)]
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
                    ...createEmptyInsight('new'),
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
            const variablesOverride = searchParams['variables_override']

            if (
                insightId !== values.insightId ||
                insightMode !== values.insightMode ||
                itemId !== values.itemId ||
                alert_id !== values.alertId ||
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
                    dashboardName
                )
            }

            let queryFromUrl: Node | null = null
            let validatingQuery = false
            if (q) {
                const validQuery = parseDraftQueryFromURL(q)
                if (validQuery) {
                    validatingQuery = true
                    actions.upgradeQuery(validQuery)
                } else {
                    console.error('Invalid query', q)
                }
            } else if (insightType && Object.values(InsightType).includes(insightType)) {
                queryFromUrl = getDefaultQuery(insightType, values.filterTestAccountsDefault)
            }

            actions.setFreshQuery(false)

            // reset the insight's state if we have to
            if ((initial || queryFromUrl || method === 'PUSH') && !validatingQuery) {
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

                    eventUsageLogic.actions.reportInsightCreated(query)
                }
            }
        },
    })),
    actionToUrl(({ values }) => {
        const actionToUrl = ({
            insightMode = values.insightMode,
            insightId = values.insightId,
        }: {
            insightMode?: ItemMode
            insightId?: InsightShortId | 'new' | null
        }): [
            string,
            string | Record<string, any> | undefined,
            string | Record<string, any> | undefined,
            { replace?: boolean }
        ] => {
            const baseUrl =
                !insightId || insightId === 'new'
                    ? urls.insightNew()
                    : insightMode === ItemMode.View
                    ? urls.insightView(insightId)
                    : urls.insightEdit(insightId)
            const searchParams = router.values.currentLocation.searchParams
            // TODO: also kepe these in the URL?
            // const metadataChanged = !!values.insightLogicRef?.logic.values.insightChanged
            const queryChanged = !!values.insightDataLogicRef?.logic.values.queryChanged
            const query = values.insightDataLogicRef?.logic.values.query
            const hashParams = queryChanged ? { q: query } : undefined

            return [baseUrl, searchParams, hashParams, { replace: true }]
        }

        return {
            setInsightId: actionToUrl,
            setInsightMode: actionToUrl,
        }
    }),
])
