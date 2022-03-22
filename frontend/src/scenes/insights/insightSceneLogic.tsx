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
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function confirmDiscardingInsightChanges(): boolean {
    const shouldDiscardChanges = confirm('Leave insight? Changes you made will be discarded.')
    if (shouldDiscardChanges) {
        insightSceneLogic.findMounted()?.values.insightCache?.logic.actions.cancelChanges()
    } else {
        history.back()
    }
    return shouldDiscardChanges
}

export const insightSceneLogic = kea<insightSceneLogicType>({
    path: ['scenes', 'insights', 'insightSceneLogic'],
    connect: {
        logic: [eventUsageLogic, featureFlagLogic],
    },
    actions: {
        createNewInsight: (filters: Partial<FilterType>, dashboardId: number | null) => ({ filters, dashboardId }),
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
        createNewInsight: async ({ filters, dashboardId }, breakpoint) => {
            const createdInsight: InsightModel = await api.create(
                `api/projects/${teamLogic.values.currentTeamId}/insights`,
                {
                    name: '',
                    description: '',
                    tags: [],
                    filters: cleanFilters(filters || {}, undefined, featureFlagLogic.values.featureFlags),
                    result: null,
                    // Not using the dashboard ID here to avoid the draft insight appearing on the dashboard IMMEDIATELY
                }
            )
            breakpoint()
            eventUsageLogic.actions.reportInsightCreated(createdInsight.filters?.insight || null)
            router.actions.replace(urls.insightEdit(createdInsight.short_id, dashboardId))
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
        '/insights/:shortId(/:mode)': ({ shortId, mode }, _, { filters, dashboard }) => {
            const insightMode = mode === 'edit' || shortId === 'new' ? ItemMode.Edit : ItemMode.View
            const insightId = String(shortId) as InsightShortId
            const oldInsightId = values.insightId
            if (insightId !== oldInsightId || insightMode !== values.insightMode) {
                // If navigating from an unsaved insight to a different insight within the scene, prompt the user
                if (
                    sceneLogic.findMounted()?.values.scene === Scene.Insight &&
                    insightId !== oldInsightId &&
                    oldInsightId !== 'new' &&
                    values.insightCache?.logic.values.filtersChanged &&
                    !confirmDiscardingInsightChanges()
                ) {
                    return
                }
                actions.setSceneState(insightId, insightMode)
                if (insightId !== oldInsightId && insightId === 'new') {
                    actions.createNewInsight(filters, dashboard)
                    return
                }
                if (dashboard) {
                    // Handle "Add insight" from dashboards by setting the dashboard ID locally
                    // Usually it's better to keep this hash param instead of stripping it after usage,
                    // just in case the user reloads the page or navigates away
                    values.insightCache?.logic.actions.setSourceDashboardId(dashboard)
                }
                // Redirect old format with filters in hash params to just /edit without params
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
