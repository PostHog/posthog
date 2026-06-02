import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DEFAULT_MDE } from '~/scenes/experiments/constants'
import { teamLogic } from '~/scenes/teamLogic'

import type { experimentsConfigLogicType } from './experimentsConfigLogicType'

export interface ExperimentsConfig {
    experiment_recalculation_time: string | null
    default_experiment_confidence_level: number | null
    default_experiment_stats_method: string | null
    default_only_count_matured_users: boolean
    default_cuped_enabled: boolean
    default_cuped_lookback_days: number | null
    default_minimum_detectable_effect: number
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
                loadExperimentsConfig: async (): Promise<ExperimentsConfig> => {
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
    selectors({
        defaultMinimumDetectableEffect: [
            (s) => [s.experimentsConfig],
            (config): number => config?.default_minimum_detectable_effect ?? DEFAULT_MDE,
        ],
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
