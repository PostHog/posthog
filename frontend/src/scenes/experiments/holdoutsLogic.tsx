import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { UserBasicType } from '~/types'

import type { holdoutsLogicType } from './holdoutsLogicType'

export interface Holdout {
    id: string
    name: string
    description: string | null
    filters: Record<string, any>
    created_by: UserBasicType | null
    created_at: string | null
    updated_at: string | null
}

export const NEW_HOLDOUT: Holdout = {
    id: 'new',
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
        updateHoldout: (id: string, holdout: Partial<Holdout>) => ({ id, holdout }),
        deleteHoldout: (id: string) => ({ id }),
        loadHoldout: (id: string) => ({ id }),
    }),
    reducers({
        holdout: [
            NEW_HOLDOUT,
            {
                setHoldout: (state, { holdout }) => ({ ...state, ...holdout }),
            },
        ],
    }),
    forms(({ actions }) => ({
        holdout: {
            defaults: { ...NEW_HOLDOUT } as Holdout,
            errors: ({ name }) => ({
                name: !name && 'Please enter a name',
            }),
            submit: () => actions.createHoldout(),
        },
    })),
    loaders(({ values }) => ({
        holdouts: [
            [] as Holdout[],
            {
                loadHoldouts: async () => {
                    const response = await api.get(`api/projects/@current/experiment_holdouts/`)
                    return response.results as Holdout[]
                },
                createHoldout: async () => {
                    const response = await api.create(`api/projects/@current/experiment_holdouts/`, values.holdout)
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
    selectors({
        holdoutById: [
            (s) => [s.holdouts],
            (holdouts: Holdout[]) => (id: string) => holdouts.find((h) => h.id === id) || null,
        ],
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadHoldouts()
        },
    })),
])
