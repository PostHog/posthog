import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { insightsApi } from '~/scenes/insights/utils/api'
import { QueryBasedInsightModel } from '~/types'

import type { customerJourneysLogicType } from './customerJourneysLogicType'

export interface CustomerJourney {
    id: string
    insight: number
    name: string
    description: string | null
    order: number
    created_at: string
    created_by: { id: number; uuid: string; distinct_id: string; first_name: string; email: string } | null
    updated_at: string
}

export const customerJourneysLogic = kea<customerJourneysLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'CustomerJourneys', 'customerJourneysLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        showAddJourneyModal: true,
        hideAddJourneyModal: true,
        deleteJourney: (journeyId: string) => ({ journeyId }),
    }),
    loaders(({ values }) => ({
        journeys: {
            __default: [] as CustomerJourney[],
            loadJourneys: async () => {
                const response = await api.get(`api/environments/${values.currentTeamId}/customer_journeys/`)
                return response.results || []
            },
            addJourney: async ({
                insightId,
                name,
                description,
            }: {
                insightId: number
                name: string
                description?: string
            }) => {
                await api.create(`api/environments/${values.currentTeamId}/customer_journeys/`, {
                    insight: insightId,
                    name,
                    description: description || null,
                    order: values.journeys.length,
                })
                const response = await api.get(`api/environments/${values.currentTeamId}/customer_journeys/`)
                return response.results || []
            },
        },
        insights: {
            __default: {} as Record<number, QueryBasedInsightModel | null>,
            loadInsights: async () => {
                const insightIds = values.journeys.map((j) => j.insight)
                const insights: Record<number, QueryBasedInsightModel | null> = {}

                await Promise.all(
                    insightIds.map(async (id) => {
                        try {
                            insights[id] = await insightsApi.getByNumericId(id)
                        } catch {
                            insights[id] = null
                        }
                    })
                )

                return insights
            },
        },
    })),
    reducers({
        isAddJourneyModalOpen: [
            false,
            {
                showAddJourneyModal: () => true,
                hideAddJourneyModal: () => false,
                addJourneySuccess: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        deleteJourney: async ({ journeyId }) => {
            await api.delete(`api/environments/${values.currentTeamId}/customer_journeys/${journeyId}/`)
            actions.loadJourneys()
        },
        loadJourneysSuccess: () => {
            actions.loadInsights()
        },
    })),
    selectors({
        sortedJourneys: [
            (s) => [s.journeys],
            (journeys): CustomerJourney[] => {
                return [...journeys].sort((a, b) => {
                    if (a.order !== b.order) {
                        return a.order - b.order
                    }
                    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
                })
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadJourneys()
    }),
])
