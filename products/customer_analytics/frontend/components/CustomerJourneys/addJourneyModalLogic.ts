import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightType, QueryBasedInsightModel } from '~/types'

import type { addJourneyModalLogicType } from './addJourneyModalLogicType'
import { customerJourneysLogic } from './customerJourneysLogic'

export const addJourneyModalLogic = kea<addJourneyModalLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'CustomerJourneys', 'addJourneyModalLogic']),
    connect(() => ({
        actions: [customerJourneysLogic, ['hideAddJourneyModal', 'addJourneySuccess']],
        values: [customerJourneysLogic, ['isAddJourneyModalOpen']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSelectedInsight: (insightId: number | null) => ({ insightId }),
        loadFunnels: true,
    }),
    lazyLoaders(({ values }) => ({
        funnels: {
            __default: [] as QueryBasedInsightModel[],
            loadFunnels: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.insights.list({
                    saved: true,
                    insight: InsightType.FUNNELS,
                    ...(values.searchTerm ? { search: values.searchTerm } : {}),
                })
                return response.results.map((insight) => getQueryBasedInsightModel(insight))
            },
        },
    })),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                hideAddJourneyModal: () => '',
            },
        ],
        selectedInsight: [
            null as number | null,
            {
                setSelectedInsight: (_, { insightId }) => insightId,
                hideAddJourneyModal: () => null,
            },
        ],
    }),
    listeners(({ actions }) => ({
        setSearchTerm: () => {
            actions.loadFunnels()
        },
        addJourneySuccess: () => {
            actions.setSelectedInsight(null)
            actions.setSearchTerm('')
        },
    })),
])
