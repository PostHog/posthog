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
        setActiveJourneyId: (journeyId: string | null) => ({ journeyId }),
        selectFirstJourneyIfNeeded: (journeys: CustomerJourney[]) => ({ journeys }),
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
        activeInsight: {
            __default: null as QueryBasedInsightModel | null,
            loadActiveInsight: async () => {
                const journey = values.activeJourney
                if (!journey) {
                    return null
                }
                return await insightsApi.getByNumericId(journey.insight)
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
        activeJourneyId: [
            null as string | null,
            {
                setActiveJourneyId: (_, { journeyId }) => journeyId,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        deleteJourney: async ({ journeyId }) => {
            await api.delete(`api/environments/${values.currentTeamId}/customer_journeys/${journeyId}/`)
            actions.loadJourneys()
        },
        loadJourneysSuccess: ({ journeys }) => {
            actions.selectFirstJourneyIfNeeded(journeys)
        },
        addJourneySuccess: ({ journeys }) => {
            actions.selectFirstJourneyIfNeeded(journeys)
        },
        selectFirstJourneyIfNeeded: ({ journeys }) => {
            if (journeys.length > 0) {
                const currentActive = values.activeJourneyId
                const stillExists = currentActive && journeys.some((j: CustomerJourney) => j.id === currentActive)
                if (!stillExists) {
                    actions.setActiveJourneyId(journeys[0].id)
                }
            } else {
                actions.setActiveJourneyId(null)
            }
        },
        setActiveJourneyId: () => {
            actions.loadActiveInsight()
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
        activeJourney: [
            (s) => [s.sortedJourneys, s.activeJourneyId],
            (journeys, activeId): CustomerJourney | null => {
                if (!activeId) {
                    return null
                }
                return journeys.find((j) => j.id === activeId) || null
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadJourneys()
    }),
])
