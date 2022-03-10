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
        newInsight: (filters: Partial<FilterType>) => ({ filters }),
        setInsightId: (insightId: InsightShortId) => ({ insightId }),
        setInsightMode: (insightMode: ItemMode, source: InsightEventSource | null) => ({ insightMode, source }),
    },
    reducers: {
        insightId: [null as null | InsightShortId, { setInsightId: (_, { insightId }) => insightId }],
        insightMode: [
            ItemMode.View as ItemMode,
            {
                setInsightMode: (_, { insightMode }) => insightMode,
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
        newInsight: async ({ filters }, breakpoint) => {
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
        [urls.insightNew()]: async (_, __, { filters }) => {
            actions.newInsight(filters)
        },
        '/insights/:shortId(/:mode)': (params) => {
            const insightId = String(params.shortId) as InsightShortId
            if (insightId !== values.insightId) {
                actions.setInsightId(insightId)
            }

            if (params.mode === 'edit' && values.insightMode === ItemMode.View) {
                actions.setInsightMode(ItemMode.Edit, InsightEventSource.Browser)
            } else if (!params.mode && values.insightMode === ItemMode.Edit) {
                actions.setInsightMode(ItemMode.View, InsightEventSource.Browser)
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
