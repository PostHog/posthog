import { actions, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'

import { InsightType, SavedFunnel } from '~/types'

import { teamLogic } from '../scenes/teamLogic'
import type { funnelsModelType } from './funnelsModelType'

const parseSavedFunnel = (result: Record<string, any>): SavedFunnel => {
    return {
        filters: result.filters,
        type: InsightType.FUNNELS,
        id: result.id,
        createdAt: result.created_at,
        name: result.name,
        saved: result.saved,
        created_by: result.created_by,
    }
}

export const funnelsModel = kea<funnelsModelType>([
    path(['models', 'funnelsModel']),
    actions(() => ({
        setNext: (next) => ({ next }),
        loadNext: true,
        appendFunnels: (funnels) => ({ funnels }),
    })),
    loaders(({ values, actions }) => ({
        funnels: {
            __default: [] as SavedFunnel[],
            loadFunnels: async () => {
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/?${toParams({
                        order: '-created_at',
                        saved: true,
                        limit: 5,
                        insight: InsightType.FUNNELS,
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
    })),
    reducers(() => ({
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
    })),
    listeners(({ values, actions }) => ({
        loadNext: async () => {
            if (!values.next) {
                throw new Error('URL of next page of funnels is not known.')
            }
            const response = await api.get(values.next)
            const results = response.results.map((result: Record<string, any>) => parseSavedFunnel(result))
            actions.setNext(response.next)
            actions.appendFunnels(results)
        },
    })),
    events(({ actions }) => ({
        afterMount: actions.loadFunnels,
    })),
])
