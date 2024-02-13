import { actions, BuiltLogic, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'
import { actionToUrl, beforeUnload, router, urlToAction } from 'kea-router'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'

import { ActivityFilters } from '~/layout/navigation-3000/sidepanel/panels/activity/activityForSceneLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { ActivityScope, Breadcrumb, FilterType, InsightShortId, InsightType, ItemMode } from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { insightDataLogicType } from './insightDataLogicType'
import type { insightSceneLogicType } from './insightSceneLogicType'
import { summarizeInsight } from './summarizeInsight'

export const insightSceneLogic = kea<insightSceneLogicType>([
    path(['scenes', 'insights', 'insightSceneLogic']),
    connect({
        logic: [eventUsageLogic],
        values: [teamLogic, ['currentTeam'], sceneLogic, ['activeScene'], preflightLogic, ['isDev']],
    }),
    actions({
        setInsightId: (insightId: InsightShortId) => ({ insightId }),
        setInsightMode: (insightMode: ItemMode, source: InsightEventSource | null) => ({ insightMode, source }),
        setSceneState: (insightId: InsightShortId, insightMode: ItemMode, subscriptionId: string | undefined) => ({
            insightId,
            insightMode,
            subscriptionId,
        }),
        setInsightLogicRef: (logic: BuiltLogic<insightLogicType> | null, unmount: null | (() => void)) => ({
            logic,
            unmount,
        }),
        setInsightDataLogicRef: (logic: BuiltLogic<insightDataLogicType> | null, unmount: null | (() => void)) => ({
            logic,
            unmount,
        }),
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
        subscriptionId: [
            null as null | number | 'new',
            {
                setSceneState: (_, { subscriptionId }) =>
                    subscriptionId !== undefined
                        ? subscriptionId === 'new'
                            ? 'new'
                            : parseInt(subscriptionId, 10)
                        : null,
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
    }),
    selectors(() => ({
        insightSelector: [(s) => [s.insightLogicRef], (insightLogicRef) => insightLogicRef?.logic.selectors.insight],
        filtersSelector: [(s) => [s.insightLogicRef], (insightLogicRef) => insightLogicRef?.logic.selectors.filters],
        insight: [(s) => [(state, props) => s.insightSelector?.(state, props)?.(state, props)], (insight) => insight],
        filters: [(s) => [(state, props) => s.filtersSelector?.(state, props)?.(state, props)], (filters) => filters],
        breadcrumbs: [
            (s) => [
                s.insightLogicRef,
                s.insight,
                s.filters,
                groupsModel.selectors.aggregationLabel,
                cohortsModel.selectors.cohortsById,
                mathsLogic.selectors.mathDefinitions,
            ],
            (insightLogicRef, insight, filters, aggregationLabel, cohortsById, mathDefinitions): Breadcrumb[] => [
                {
                    key: Scene.SavedInsights,
                    name: 'Product analytics',
                    path: urls.savedInsights(),
                },
                {
                    key: [Scene.Insight, insight?.short_id || 'new'],
                    name:
                        insight?.name ||
                        summarizeInsight(insight?.query, filters, {
                            aggregationLabel,
                            cohortsById,
                            mathDefinitions,
                        }),
                    onRename: async (name: string) => {
                        await insightLogicRef?.logic.asyncActions.setInsightMetadata({ name })
                    },
                },
            ],
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
            }
        },
    })),
    listeners(({ sharedListeners }) => ({
        setInsightMode: sharedListeners.reloadInsightLogic,
        setSceneState: sharedListeners.reloadInsightLogic,
    })),
    urlToAction(({ actions, values }) => ({
        '/insights/:shortId(/:mode)(/:subscriptionId)': (
            { shortId, mode, subscriptionId }, // url params
            { dashboard, ...searchParams }, // search params
            { filters: _filters, q }, // hash params
            { method, initial } // "location changed" event payload
        ) => {
            const insightMode =
                mode === 'subscriptions'
                    ? ItemMode.Subscriptions
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

            if (
                insightId !== values.insightId ||
                insightMode !== values.insightMode ||
                subscriptionId !== values.subscriptionId
            ) {
                actions.setSceneState(insightId, insightMode, subscriptionId)
            }

            // capture any filters from the URL, either #filters={} or ?insight=X&bla=foo&bar=baz
            const filters: Partial<FilterType> | null =
                Object.keys(_filters || {}).length > 0 ? _filters : searchParams.insight ? searchParams : null

            // Redirect to a simple URL if we had filters in the URL
            if (filters || q) {
                router.actions.replace(
                    insightId === 'new'
                        ? urls.insightNew(undefined, dashboard)
                        : insightMode === ItemMode.Edit
                        ? urls.insightEdit(insightId)
                        : urls.insightView(insightId)
                )
            }

            // reset the insight's state if we have to
            if (initial || method === 'PUSH' || filters || q) {
                if (insightId === 'new') {
                    const teamFilterTestAccounts = values.currentTeam?.test_account_filters_default_checked || false
                    values.insightLogicRef?.logic.actions.setInsight(
                        {
                            ...createEmptyInsight('new', teamFilterTestAccounts),
                            ...(filters ? { filters: cleanFilters(filters || {}, teamFilterTestAccounts) } : {}),
                            ...(dashboard ? { dashboards: [dashboard] } : {}),
                            ...(q ? { query: JSON.parse(q) } : {}),
                        },
                        {
                            fromPersistentApi: false,
                            overrideFilter: true,
                        }
                    )

                    eventUsageLogic.actions.reportInsightCreated(filters?.insight || InsightType.TRENDS)
                }
            }

            // show a warning toast if opened `/edit#filters={...}`
            if (filters && insightMode === ItemMode.Edit && insightId !== 'new') {
                lemonToast.info(`This insight has unsaved changes! Click "Save" to not lose them.`)
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
        enabled: () => {
            // safeguard against running this check on other scenes
            if (values.activeScene !== Scene.Insight) {
                return false
            }

            if (values.isDev) {
                // TRICKY: We disable beforeUnload handling in dev, but ONLY for insights
                return false
            }

            return (
                values.insightMode === ItemMode.Edit &&
                (!!values.insightLogicRef?.logic.values.insightChanged ||
                    !!values.insightDataLogicRef?.logic.values.queryChanged)
            )
        },
        message: 'Leave insight?\nChanges you made will be discarded.',
        onConfirm: () => {
            values.insightLogicRef?.logic.actions.cancelChanges()
            values.insightDataLogicRef?.logic.actions.cancelChanges()
        },
    })),
])
