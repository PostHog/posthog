import { actions, BuiltLogic, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'
import { actionToUrl, beforeUnload, router, urlToAction } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'
import { objectsEqual } from 'lib/utils'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'

import { ActivityFilters } from '~/layout/navigation-3000/sidepanel/panels/activity/activityForSceneLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { Node } from '~/queries/schema'
import { isInsightVizNode } from '~/queries/utils'
import { ActivityScope, Breadcrumb, InsightShortId, InsightType, ItemMode } from '~/types'

import { getDefaultQuery, insightDataLogic } from './insightDataLogic'
import { insightDataLogicType } from './insightDataLogicType'
import type { insightSceneLogicType } from './insightSceneLogicType'
import { summarizeInsight } from './summarizeInsight'
import { compareFilters } from './utils/compareFilters'

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
        setSceneState: (insightId: InsightShortId, insightMode: ItemMode, itemId: string | undefined) => ({
            insightId,
            insightMode,
            itemId,
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
            null as null | number | 'new',
            {
                setSceneState: (_, { itemId }) =>
                    itemId !== undefined ? (itemId === 'new' ? 'new' : parseInt(itemId, 10)) : null,
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
        legacyInsightSelector: [
            (s) => [s.insightLogicRef],
            (insightLogicRef) => insightLogicRef?.logic.selectors.legacyInsight,
        ],
        legacyInsight: [
            (s) => [(state, props) => s.legacyInsightSelector?.(state, props)?.(state, props)],
            (insight) => insight,
        ],
        queryBasedInsightSelector: [
            (s) => [s.insightLogicRef],
            (insightLogicRef) => insightLogicRef?.logic.selectors.queryBasedInsight,
        ],
        queryBasedInsight: [
            (s) => [(state, props) => s.queryBasedInsightSelector?.(state, props)?.(state, props)],
            (insight) => insight,
        ],
        breadcrumbs: [
            (s) => [
                s.insightLogicRef,
                s.queryBasedInsight,
                groupsModel.selectors.aggregationLabel,
                cohortsModel.selectors.cohortsById,
                mathsLogic.selectors.mathDefinitions,
            ],
            (insightLogicRef, insight, aggregationLabel, cohortsById, mathDefinitions): Breadcrumb[] => {
                return [
                    {
                        key: Scene.SavedInsights,
                        name: 'Product analytics',
                        path: urls.savedInsights(),
                    },
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
            (s) => [s.queryBasedInsight],
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
            const logicInsightId = values.queryBasedInsight?.short_id ?? null
            const insightId = values.insightId ?? null

            if (logicInsightId !== insightId) {
                const oldRef = values.insightLogicRef // free old logic after mounting new one
                const oldRef2 = values.insightDataLogicRef // free old logic after mounting new one
                if (insightId) {
                    const insightProps = { dashboardItemId: insightId }

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
            } else if (insightId && !values.queryBasedInsight?.result) {
                values.insightLogicRef?.logic.actions.loadInsight(insightId as InsightShortId)
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
            { dashboard, ...searchParams }, // search params
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

            if (insightId !== values.insightId || insightMode !== values.insightMode || itemId !== values.itemId) {
                actions.setSceneState(insightId, insightMode, itemId)
            }

            let query: Node | null = null
            if (q) {
                query = JSON.parse(q)
            } else if (insightType && Object.values(InsightType).includes(insightType)) {
                query = getDefaultQuery(insightType, values.filterTestAccountsDefault)
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
            if (initial || method === 'PUSH' || query) {
                if (insightId === 'new') {
                    const teamFilterTestAccounts = values.currentTeam?.test_account_filters_default_checked || false
                    values.insightLogicRef?.logic.actions.setInsight(
                        {
                            ...createEmptyInsight('new', teamFilterTestAccounts),
                            ...(dashboard ? { dashboards: [dashboard] } : {}),
                            ...(query ? { query } : {}),
                        },
                        {
                            fromPersistentApi: false,
                            overrideFilter: true,
                        }
                    )

                    actions.setOpenedWithQuery(query || null)

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
    beforeUnload(({ values, props }) => ({
        enabled: (newLocation?: CombinedLocation) => {
            // safeguard against running this check on other scenes
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

            let newInsightEdited = false
            if (props.dashboardItemId === 'new') {
                const startingQuery =
                    values.openedWithQuery || getDefaultQuery(InsightType.TRENDS, values.filterTestAccountsDefault)
                const currentQuery = values.insightDataLogicRef?.logic.values.query

                if (isInsightVizNode(startingQuery) && isInsightVizNode(currentQuery)) {
                    // TODO: This shouldn't be necessary after we have removed the `cleanFilters` function.
                    // Currently this causes "default" properties to be set on the query.
                    const startingFilters = queryNodeToFilter(startingQuery.source)
                    const currentFilters = queryNodeToFilter(currentQuery.source)

                    if (
                        currentFilters.filter_test_accounts === false &&
                        currentFilters.filter_test_accounts === values.filterTestAccountsDefault
                    ) {
                        delete currentFilters.filter_test_accounts
                    }

                    newInsightEdited = !compareFilters(
                        startingFilters,
                        currentFilters,
                        values.filterTestAccountsDefault
                    )
                } else if (!isInsightVizNode(startingQuery) && !isInsightVizNode(currentQuery)) {
                    newInsightEdited = !objectsEqual(startingQuery, currentQuery)
                } else {
                    newInsightEdited = true
                }
            }

            const insightMetadataEdited = !!values.insightLogicRef?.logic.values.insightChanged
            const savedInsightEdited =
                props.dashboardItemId !== 'new' && !!values.insightDataLogicRef?.logic.values.queryChanged

            return (
                values.insightMode === ItemMode.Edit &&
                (insightMetadataEdited || savedInsightEdited || newInsightEdited)
            )
        },
        message: 'Leave insight?\nChanges you made will be discarded.',
        onConfirm: () => {
            values.insightLogicRef?.logic.actions.cancelChanges()
            values.insightDataLogicRef?.logic.actions.cancelChanges()
        },
    })),
])
