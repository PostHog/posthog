import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { experimentsConfigLogicType } from './experimentsConfigLogicType'

export interface ExperimentsConfig {
    experiment_recalculation_time: string | null
    default_experiment_confidence_level: number | null
    default_experiment_stats_method: string | null
}

export const experimentsConfigLogic = kea<experimentsConfigLogicType>([
    path(['scenes', 'settings', 'environment', 'experimentsConfigLogic']),
    actions({
        updateExperimentsConfig: (payload: Partial<ExperimentsConfig>) => ({ payload }),
    }),
    loaders({
        experimentsConfig: [
            null as ExperimentsConfig | null,
            {
                loadExperimentsConfig: async () => {
                    return await api.get('api/environments/@current/experiments_config/')
                },
            },
        ],
    }),
    reducers({
        experimentsConfig: {
            updateExperimentsConfig: (state, { payload }) => (state ? { ...state, ...payload } : state),
        },
    }),
    listeners(({ actions }) => ({
        updateExperimentsConfig: async ({ payload }) => {
            try {
                await api.update('api/environments/@current/experiments_config/', payload)
            } finally {
                actions.loadExperimentsConfig()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadExperimentsConfig()
    }),
])
