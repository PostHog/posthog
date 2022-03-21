import { BuiltLogic, kea } from 'kea'
import { Breadcrumb, InsightModel, InsightShortId, ItemMode } from '~/types'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { router } from 'kea-router'
import { insightSceneLogicType } from './insightSceneLogicType'
import { urls } from 'scenes/urls'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
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
        '/insights/:shortId(/:mode)': ({ shortId, mode }, _, { filters }, { method, initial }) => {
            const insightMode = mode === 'edit' || shortId === 'new' ? ItemMode.Edit : ItemMode.View
            const insightId = String(shortId) as InsightShortId
            const oldInsightId = values.insightId
            if (insightId !== oldInsightId || insightMode !== values.insightMode) {
                actions.setSceneState(insightId, insightMode)
            }
            if (filters && Object.keys(filters).length > 0) {
                // Redirect #filters={} to just /new or /edit.
                values.insightCache?.logic.actions.setFilters(filters)
                router.actions.replace(insightId === 'new' ? urls.insightNew() : urls.insightEdit(insightId))
                lemonToast.info(`This insight has unsaved changes! Click "Save" to not lose them.`)
            } else if (insightId === 'new' && (method === 'PUSH' || initial)) {
                // if opening the site on /insights/new or clicked on a new button, clear new page
                values.insightCache?.logic.actions.setFilters(cleanFilters({}))
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
