import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect/LemonSelect'

import { isInsightVizNode } from '~/queries/utils'
import { insightsApi } from '~/scenes/insights/utils/api'
import { QueryBasedInsightModel } from '~/types'

import { CustomerJourneyApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { customerJourneysLogicType } from './customerJourneysLogicType'

export const customerJourneysLogic = kea<customerJourneysLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'CustomerJourneys', 'customerJourneysLogic']),
    actions({
        showAddJourneyModal: true,
        hideAddJourneyModal: true,
        setActiveJourneyId: (journeyId: string | null) => ({ journeyId }),
        selectFirstJourneyIfNeeded: (journeys: CustomerJourneyApi[]) => ({ journeys }),
        deleteJourney: (journeyId: string) => ({ journeyId }),
    }),
    lazyLoaders(({ values }) => ({
        journeys: {
            __default: [] as CustomerJourneyApi[],
            loadJourneys: async (): Promise<CustomerJourneyApi[]> => {
                const response = await api.customerJourneys.list()
                return response.results
            },
            addJourney: async ({
                insightId,
                name,
                description,
            }: {
                insightId: number
                name: string
                description?: string
            }): Promise<CustomerJourneyApi[]> => {
                await api.customerJourneys.create({ insight: insightId, name, description })
                const response = await api.customerJourneys.list()
                return response.results
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
            await api.customerJourneys.delete(journeyId)
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
                const stillExists = currentActive && journeys.some((j: CustomerJourneyApi) => j.id === currentActive)
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
        journeyOptions: [
            (s) => [s.journeys],
            (journeys): LemonSelectOptions<string> =>
                journeys.map((journey) => ({
                    value: journey.id,
                    label: journey.name,
                })),
        ],
        activeJourney: [
            (s) => [s.journeys, s.activeJourneyId],
            (journeys, activeId): CustomerJourneyApi | null => {
                if (!activeId) {
                    return null
                }
                return journeys.find((j) => j.id === activeId) || null
            },
        ],
        activeJourneyFullQuery: [
            (s) => [s.activeInsight],
            (activeInsight) => {
                const query = activeInsight?.query
                return query && isInsightVizNode(query) ? { ...query, full: true } : query
            },
        ],
    }),
])
