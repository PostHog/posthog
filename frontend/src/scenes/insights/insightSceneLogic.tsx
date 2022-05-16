import { BuiltLogic, kea } from 'kea'
import { Breadcrumb, FilterType, InsightShortId, InsightType, ItemMode } from '~/types'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { router } from 'kea-router'
import type { insightSceneLogicType } from './insightSceneLogicType'
import { urls } from 'scenes/urls'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

/** Return null if there are no changes to be discarded, false if user confirmed discarding, and true if rejected. */
export function preventDiscardingInsightChanges(): boolean | null {
    let shouldPreventNavigatingAway: boolean | null = null
    let shouldCancelChanges: boolean = false
    const mountedInsightSceneLogic = insightSceneLogic.findMounted()
    if (mountedInsightSceneLogic?.values.syncedInsightChanged) {
        // Cancel changes automatically if not in edit mode
        shouldCancelChanges = mountedInsightSceneLogic?.values.insightMode !== ItemMode.Edit
        if (!shouldCancelChanges) {
            // If in edit mode, make sure cancelling changes is OK, and prevent navigation if it isn't
            shouldCancelChanges = confirm('Leave insight? Changes you made will be discarded.')
            shouldPreventNavigatingAway = !shouldCancelChanges
        }
        if (shouldCancelChanges) {
            mountedInsightSceneLogic?.values.insightCache?.logic.actions.cancelChanges()
        }
    }
    return shouldPreventNavigatingAway
}

export const insightSceneLogic = kea<insightSceneLogicType>({
    path: ['scenes', 'insights', 'insightSceneLogic'],
    connect: {
        logic: [eventUsageLogic],
    },
    actions: {
        setInsightId: (insightId: InsightShortId) => ({ insightId }),
        setInsightMode: (insightMode: ItemMode, source: InsightEventSource | null) => ({ insightMode, source }),
        setSceneState: (insightId: InsightShortId, insightMode: ItemMode) => ({
            insightId,
            insightMode,
        }),
        setInsightLogic: (logic: BuiltLogic<insightLogicType> | null, unmount: null | (() => void)) => ({
            logic,
            unmount,
        }),
        syncInsightChanged: (syncedInsightChanged: boolean) => ({ syncedInsightChanged }),
    },
    reducers: {
        insightId: [
            null as null | 'new' | InsightShortId,
            {
                setInsightId: (_, { insightId }) => insightId,
                setSceneState: (_, { insightId }) => insightId,
            },
        ],
        insightMode: [
            ItemMode.View as ItemMode,
            {
                setInsightMode: (_, { insightMode }) => insightMode,
                setSceneState: (_, { insightMode }) => insightMode,
            },
        ],
        syncedInsightChanged: [
            // Connecting `insightChanged` via `insightCache.logic.selectors` sometimes gives stale values,
            // so instead saving the up-to-date value right in this logic with a `useEffect` in the `Insight` component
            false,
            {
                syncInsightChanged: (_, { syncedInsightChanged }) => syncedInsightChanged,
            },
        ],
        lastInsightModeSource: [
            null as InsightEventSource | null,
            {
                setInsightMode: (_, { source }) => source,
            },
        ],
        insightCache: [
            null as null | {
                logic: BuiltLogic<insightLogicType>
                unmount: () => void
            },
            {
                setInsightLogic: (_, { logic, unmount }) => (logic && unmount ? { logic, unmount } : null),
            },
        ],
    },
    selectors: () => ({
        insightSelector: [(s) => [s.insightCache], (insightCache) => insightCache?.logic.selectors.insight],
        insight: [(s) => [(state, props) => s.insightSelector?.(state, props)?.(state, props)], (insight) => insight],
        breadcrumbs: [
            (s) => [s.insight],
            (insight): Breadcrumb[] => [
                {
                    name: 'Insights',
                    path: urls.savedInsights(),
                },
                {
                    name: insight?.name || insight?.derived_name || 'Unnamed',
                },
            ],
        ],
    }),
    listeners: ({ sharedListeners }) => ({
        setInsightMode: sharedListeners.reloadInsightLogic,
        setSceneState: sharedListeners.reloadInsightLogic,
    }),
    sharedListeners: ({ actions, values }) => ({
        reloadInsightLogic: () => {
            const logicInsightId = values.insight?.short_id ?? null
            const insightId = values.insightId ?? null

            if (logicInsightId !== insightId) {
                const oldCache = values.insightCache // free old logic after mounting new one
                if (insightId) {
                    const logic = insightLogic.build({ dashboardItemId: insightId })
                    const unmount = logic.mount()
                    actions.setInsightLogic(logic, unmount)
                } else {
                    actions.setInsightLogic(null, null)
                }
                if (oldCache) {
                    oldCache.unmount()
                }
            }
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights/:shortId(/:mode)': (
            { shortId, mode }, // url params
            { dashboard, ...searchParams }, // search params
            { filters: _filters }, // hash params
            { method, initial } // "location changed" event payload
        ) => {
            const insightMode = mode === 'edit' || shortId === 'new' ? ItemMode.Edit : ItemMode.View
            const insightId = String(shortId) as InsightShortId

            // If navigating from an unsaved insight to a different insight within the scene, prompt the user
            if (
                sceneLogic.findMounted()?.values.scene === Scene.Insight &&
                method === 'PUSH' &&
                (values.insightId === 'new' || insightId !== values.insightId) &&
                preventDiscardingInsightChanges()
            ) {
                return
            }

            // this makes sure we have "values.insightCache?.logic" below
            if (insightId !== values.insightId || insightMode !== values.insightMode) {
                actions.setSceneState(insightId, insightMode)
            }

            // capture any filters from the URL, either #filters={} or ?insight=X&bla=foo&bar=baz
            const filters: Partial<FilterType> | null =
                Object.keys(_filters || {}).length > 0 ? _filters : searchParams.insight ? searchParams : null

            // reset the insight's state if we have to
            if (initial || method === 'PUSH' || filters) {
                if (insightId === 'new') {
                    values.insightCache?.logic.actions.setInsight(
                        {
                            ...createEmptyInsight('new'),
                            ...(filters ? { filters: cleanFilters(filters || {}) } : {}),
                            ...(dashboard ? { dashboards: [dashboard] } : {}),
                        },
                        {
                            fromPersistentApi: false,
                            overrideFilter: true,
                            shouldMergeWithExisting: false,
                        }
                    )
                    values.insightCache?.logic.actions.loadResults()
                    eventUsageLogic.actions.reportInsightCreated(filters?.insight || InsightType.TRENDS)
                } else if (filters) {
                    values.insightCache?.logic.actions.setFilters(cleanFilters(filters || {}))
                }
            }

            // Redirect to a simple URL if we had filters in the URL
            if (filters) {
                router.actions.replace(
                    insightId === 'new'
                        ? urls.insightNew(undefined, dashboard)
                        : insightMode === ItemMode.Edit
                        ? urls.insightEdit(insightId)
                        : urls.insightView(insightId)
                )
            }

            // show a warning toast if opened `/edit#filters={...}`
            if (filters && insightMode === ItemMode.Edit && insightId !== 'new') {
                lemonToast.info(`This insight has unsaved changes! Click "Save" to not lose them.`)
            }
        },
    }),
    actionToUrl: ({ values }) => {
        const actionToUrl = (): string | undefined =>
            values.insightId && values.insightId !== 'new'
                ? values.insightMode === ItemMode.View
                    ? urls.insightView(values.insightId)
                    : urls.insightEdit(values.insightId)
                : undefined

        return {
            setInsightId: actionToUrl,
            setInsightMode: actionToUrl,
        }
    },
})
