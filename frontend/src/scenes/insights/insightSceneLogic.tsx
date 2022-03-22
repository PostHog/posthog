import { BuiltLogic, kea } from 'kea'
import { Breadcrumb, FilterType, InsightModel, InsightShortId, InsightType, ItemMode } from '~/types'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { router } from 'kea-router'
import { insightSceneLogicType } from './insightSceneLogicType'
import { urls } from 'scenes/urls'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { createEmptyInsight, insightLogic } from 'scenes/insights/insightLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

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
        setInsightLogic: (
            logic: BuiltLogic<insightLogicType> | null,
            selector: ((state: any, props: any) => Partial<InsightModel>) | null,
            unmount: null | (() => void)
        ) => ({
            logic,
            selector,
            unmount,
        }),
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
        lastInsightModeSource: [
            null as InsightEventSource | null,
            {
                setInsightMode: (_, { source }) => source,
            },
        ],
        insightCache: [
            null as null | {
                logic: BuiltLogic<insightLogicType>
                selector: (state: any, props: any) => Partial<InsightModel> | null
                unmount: () => void
            },
            {
                setInsightLogic: (_, { logic, selector, unmount }) =>
                    logic && selector && unmount ? { logic, selector, unmount } : null,
            },
        ],
    },
    selectors: () => ({
        insightSelector: [(s) => [s.insightCache], (insightCache) => insightCache?.selector],
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
                    const logic = insightLogic.build({ dashboardItemId: insightId }, false)
                    const unmount = logic.mount()
                    const selector = logic.selectors.insight
                    actions.setInsightLogic(logic, selector, unmount)
                } else {
                    actions.setInsightLogic(null, null, null)
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
                            ...(dashboard ? { dashboard } : {}),
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
