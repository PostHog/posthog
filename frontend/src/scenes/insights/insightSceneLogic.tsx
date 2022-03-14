import { kea, BuiltLogic } from 'kea'
import { Breadcrumb, FilterType, InsightModel, InsightShortId, ItemMode } from '~/types'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { router } from 'kea-router'
import { insightSceneLogicType } from './insightSceneLogicType'
import { urls } from 'scenes/urls'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { insightLogicType } from 'scenes/insights/insightLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { lemonToast } from 'lib/components/lemonToast'

export const insightSceneLogic = kea<insightSceneLogicType>({
    path: ['scenes', 'insights', 'insightSceneLogic'],
    connect: {
        logic: [eventUsageLogic],
    },
    actions: {
        createNewInsight: (filters: Partial<FilterType>) => ({ filters }),
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
                createNewInsight: () => ItemMode.Edit,
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
                    name: insight?.id ? insight.name || insight.derived_name || 'Unnamed' : null,
                },
            ],
        ],
    }),
    listeners: ({ sharedListeners }) => ({
        createNewInsight: async ({ filters }, breakpoint) => {
            const createdInsight: InsightModel = await api.create(
                `api/projects/${teamLogic.values.currentTeamId}/insights`,
                {
                    name: '',
                    description: '',
                    tags: [],
                    filters: cleanFilters(filters || {}),
                    result: null,
                }
            )
            breakpoint()
            eventUsageLogic.actions.reportInsightCreated(createdInsight.filters?.insight || null)
            router.actions.replace(urls.insightEdit(createdInsight.short_id))
        },
        setInsightMode: sharedListeners.reloadInsightLogic,
        setSceneState: sharedListeners.reloadInsightLogic,
    }),
    sharedListeners: ({ actions, values }) => ({
        reloadInsightLogic: () => {
            const logicInsightId = values.insight?.short_id ?? null
            const insightId = values.insightId !== 'new' ? values.insightId ?? null : null

            if (logicInsightId !== insightId) {
                const oldCache = values.insightCache // free old logic after mounting new one
                if (insightId) {
                    const logic = insightLogic({ dashboardItemId: insightId })
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
        '/insights/:shortId(/:mode)': ({ shortId, mode }, _, { filters }) => {
            const insightMode = mode === 'edit' || shortId === 'new' ? ItemMode.Edit : ItemMode.View
            const insightId = String(shortId) as InsightShortId
            const oldInsightId = values.insightId
            if (insightId !== oldInsightId || insightMode !== values.insightMode) {
                actions.setSceneState(insightId, insightMode)
                if (insightId !== oldInsightId && insightId === 'new') {
                    actions.createNewInsight(filters)
                    return
                }
                // Redirect #filters={} to just /edit.
                if (filters && Object.keys(filters).length > 0) {
                    values.insightCache?.logic.actions.setFilters(filters)
                    router.actions.replace(urls.insightEdit(insightId))
                    lemonToast.info(`This insight has unsaved changes! Click "Save" to not lose them.`)
                }
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
