import { kea } from 'kea'
import { FilterType, InsightModel, InsightShortId, ItemMode } from '~/types'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { router } from 'kea-router'
import { insightSceneLogicType } from './insightSceneLogicType'
import { urls } from 'scenes/urls'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

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
    },
    reducers: {
        insightId: [
            null as null | InsightShortId,
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
    },
    listeners: () => ({
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
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights/:shortId(/:mode)': ({ shortId, mode }, _, { filters }) => {
            const insightMode = mode === 'edit' || shortId === 'new' ? ItemMode.Edit : ItemMode.View
            const insightId = String(shortId) as InsightShortId
            const oldInsightId = values.insightId
            if (insightId !== values.insightId || insightMode !== values.insightMode) {
                actions.setSceneState(insightId, insightMode)
                if (insightId !== oldInsightId && insightId === 'new') {
                    actions.createNewInsight(filters)
                }
            }
        },
    }),

    actionToUrl: ({ values }) => {
        const actionToUrl = (): string | undefined =>
            values.insightId
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
