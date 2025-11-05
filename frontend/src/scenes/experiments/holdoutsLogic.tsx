import { actions, connect, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { ExperimentHoldoutType } from '~/types'

import type { holdoutsLogicType } from './holdoutsLogicType'

export const NEW_HOLDOUT: ExperimentHoldoutType = {
    id: null,
    name: '',
    description: null,
    filters: [
        {
            properties: [],
            rollout_percentage: 10,
            variant: 'holdout',
        },
    ],
    created_by: null,
    created_at: null,
    updated_at: null,
}

export const holdoutsLogic = kea<holdoutsLogicType>([
    path(['scenes', 'experiments', 'holdoutsLogic']),
    actions({
        setHoldout: (holdout: Partial<ExperimentHoldoutType>) => ({ holdout }),
        createHoldout: true,
        updateHoldout: (id: number | null, holdout: Partial<ExperimentHoldoutType>) => ({ id, holdout }),
        deleteHoldout: (id: number | null) => ({ id }),
        loadHoldout: (id: number | null) => ({ id }),
    }),
    connect(() => ({
        actions: [eventUsageLogic, ['reportExperimentHoldoutCreated']],
    })),
    reducers({
        holdout: [
            NEW_HOLDOUT,
            {
                setHoldout: (state, { holdout }) => ({ ...state, ...holdout }),
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        holdouts: [
            [] as ExperimentHoldoutType[],
            {
                loadHoldouts: async () => {
                    const response = await api.get(`api/projects/@current/experiment_holdouts/`)
                    return response.results as ExperimentHoldoutType[]
                },
                createHoldout: async () => {
                    const response = await api.create(`api/projects/@current/experiment_holdouts/`, values.holdout)
                    actions.reportExperimentHoldoutCreated(response)
                    return [...values.holdouts, response] as ExperimentHoldoutType[]
                },
                updateHoldout: async ({ id, holdout }) => {
                    const response = await api.update(`api/projects/@current/experiment_holdouts/${id}/`, holdout)
                    return values.holdouts.map((h) => (h.id === id ? response : h)) as ExperimentHoldoutType[]
                },
                deleteHoldout: async ({ id }) => {
                    await api.delete(`api/projects/@current/experiment_holdouts/${id}/`)
                    return values.holdouts.filter((h) => h.id !== id)
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        createHoldoutSuccess: () => {
            lemonToast.success('Holdout created')
            actions.loadHoldouts()
        },
        updateHoldoutSuccess: () => {
            lemonToast.success('Holdout updated')
            actions.loadHoldouts()
        },
        deleteHoldoutSuccess: () => {
            lemonToast.success('Holdout deleted')
            actions.loadHoldouts()
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadHoldouts()
        },
    })),
])
