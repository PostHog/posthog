import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { SavedFunnel, ViewType } from '~/types'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { funnelsModelType } from './funnelsModelType'
import { teamLogic } from '../scenes/teamLogic'

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

export const funnelsModel = kea<funnelsModelType>({
    loaders: ({ values, actions }) => ({
        funnels: {
            __default: [] as SavedFunnel[],
            loadFunnels: async () => {
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/?${toParams({
                        order: '-created_at',
                        saved: true,
                        limit: 5,
                        insight: ViewType.FUNNELS,
                    })}`
                )
                const results = response.results.map((result: Record<string, any>) => parseSavedFunnel(result))
                actions.setNext(response.next)
                return results
            },
            deleteFunnel: async (funnelId: number) => {
                await api.delete(`api/projects/${teamLogic.values.currentTeamId}/insights/${funnelId}`)
                return values.funnels.filter((funnel) => funnel.id !== funnelId)
            },
        },
    }),
    connect: {
        actions: [insightHistoryLogic, ['updateInsight']],
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
            const results = response.results.map((result: Record<string, any>) => parseSavedFunnel(result))
            actions.setNext(response.next)
            actions.appendFunnels(results)
        },
        updateInsight: () => actions.loadFunnels(),
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadFunnels,
    }),
})
