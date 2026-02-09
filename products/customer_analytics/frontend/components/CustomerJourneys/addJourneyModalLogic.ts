import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel, InsightType, QueryBasedInsightModel } from '~/types'

import type { addJourneyModalLogicType } from './addJourneyModalLogicType'
import { customerJourneysLogic } from './customerJourneysLogic'

export const addJourneyModalLogic = kea<addJourneyModalLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'CustomerJourneys', 'addJourneyModalLogic']),
    connect(() => ({
        actions: [customerJourneysLogic, ['hideAddJourneyModal']],
        values: [teamLogic, ['currentTeamId'], customerJourneysLogic, ['isAddJourneyModalOpen']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSelectedInsight: (insightId: number | null) => ({ insightId }),
    }),
    loaders(({ values }) => ({
        funnels: {
            __default: [] as QueryBasedInsightModel[],
            loadFunnels: async (_, breakpoint) => {
                await breakpoint(300)
                const response: { results: InsightModel[] } = await api.get(
                    `api/environments/${values.currentTeamId}/insights/?saved=true&insight=${InsightType.FUNNELS}${
                        values.searchTerm ? `&search=${encodeURIComponent(values.searchTerm)}` : ''
                    }`
                )
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
        [customerJourneysLogic.actionTypes.showAddJourneyModal]: () => {
            actions.loadFunnels()
        },
        [customerJourneysLogic.actionTypes.addJourneySuccess]: () => {
            actions.setSelectedInsight(null)
            actions.setSearchTerm('')
        },
    })),
])
