import { actions, connect, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { UserBasicType } from '~/types'

import type { holdoutsLogicType } from './holdoutsLogicType'

export interface Holdout {
    id: number | null
    name: string
    description: string | null
    filters: Record<string, any>
    created_by: UserBasicType | null
    created_at: string | null
    updated_at: string | null
}

export const NEW_HOLDOUT: Holdout = {
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
        setHoldout: (holdout: Partial<Holdout>) => ({ holdout }),
        createHoldout: true,
        updateHoldout: (id: number | null, holdout: Partial<Holdout>) => ({ id, holdout }),
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
            [] as Holdout[],
            {
                loadHoldouts: async () => {
                    const response = await api.get(`api/projects/@current/experiment_holdouts/`)
                    return response.results as Holdout[]
                },
                createHoldout: async () => {
                    const response = await api.create(`api/projects/@current/experiment_holdouts/`, values.holdout)
                    actions.reportExperimentHoldoutCreated(response)
                    return [...values.holdouts, response] as Holdout[]
                },
                updateHoldout: async ({ id, holdout }) => {
                    const response = await api.update(`api/projects/@current/experiment_holdouts/${id}/`, holdout)
                    return values.holdouts.map((h) => (h.id === id ? response : h)) as Holdout[]
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
