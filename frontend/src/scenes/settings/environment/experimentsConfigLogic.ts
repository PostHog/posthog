import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { teamLogic } from '~/scenes/teamLogic'

import type { experimentsConfigLogicType } from './experimentsConfigLogicType'

export interface ExperimentsConfig {
    experiment_recalculation_time: string | null
    default_experiment_confidence_level: number | null
    default_experiment_stats_method: string | null
    default_only_count_matured_users: boolean
}

export const experimentsConfigLogic = kea<experimentsConfigLogicType>([
    path(['scenes', 'settings', 'environment', 'experimentsConfigLogic']),
    connect({ values: [teamLogic, ['currentTeamId']] }),
    actions({
        updateExperimentsConfig: (payload: Partial<ExperimentsConfig>) => ({ payload }),
    }),
    loaders(({ values }) => ({
        experimentsConfig: [
            null as ExperimentsConfig | null,
            {
                loadExperimentsConfig: async () => {
                    return await api.get(`api/environments/${values.currentTeamId}/experiments_config/`)
                },
            },
        ],
    })),
    reducers({
        experimentsConfig: {
            updateExperimentsConfig: (state, { payload }) => (state ? { ...state, ...payload } : state),
        },
    }),
    listeners(({ actions, values }) => ({
        updateExperimentsConfig: async ({ payload }) => {
            try {
                await api.update(`api/environments/${values.currentTeamId}/experiments_config/`, payload)
            } finally {
                actions.loadExperimentsConfig()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadExperimentsConfig()
    }),
])
