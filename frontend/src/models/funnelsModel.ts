import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { ViewType } from 'scenes/insights/insightLogic'
import { DashboardItemType, SavedFunnel } from '~/types'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { funnelsModelType } from './funnelsModelType'

const parseSavedFunnel = (result: Record<string, any>): SavedFunnel => {
    return {
        filters: result.filters,
        type: ViewType.FUNNELS,
        id: result.id,
        createdAt: result.created_at,
        name: result.name,
        saved: result.saved,
        created_by: result.created_by,
    }
}

export const funnelsModel = kea<funnelsModelType<SavedFunnel, DashboardItemType>>({
    loaders: ({ actions }) => ({
        funnels: {
            __default: [] as SavedFunnel[],
            loadFunnels: async () => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: '-created_at',
                            saved: true,
                            limit: 5,
                            insight: ViewType.FUNNELS,
                        })
                )
                const result = response.results.map((result: Record<string, any>) => parseSavedFunnel(result))
                actions.setNext(response.next)
                return result
            },
        },
    }),
    connect: {
        actions: [insightHistoryLogic, ['updateInsight'], funnelLogic, ['saveFunnelInsight']],
    },
    reducers: () => ({
        next: [
            null as null | string,
            {
                setNext: (_, { next }) => next,
            },
        ],
        funnels: {
            appendFunnels: (state, { funnels }) => [...state, ...funnels],
        },
        loadingMore: [
            false,
            {
                loadNext: () => true,
                setNext: () => false,
            },
        ],
    }),
    actions: () => ({
        setNext: (next) => ({ next }),
        loadNext: true,
        appendFunnels: (funnels) => ({ funnels }),
    }),
    listeners: ({ values, actions }) => ({
        loadNext: async () => {
            const response = await api.get(values.next)
            const result = response.results.map((result: Record<string, any>) => parseSavedFunnel(result))
            actions.setNext(response.next)
            actions.appendFunnels(result)
        },
        updateInsight: () => actions.loadFunnels(),
        saveFunnelInsight: () => actions.loadFunnels(),
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadFunnels,
    }),
})
