import { actions, events, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
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
    filters: {},
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
                    // Dummy implementation
                    return [
                        {
                            id: '1',
                            name: 'Holdout 1',
                            description: 'First holdout',
                            filters: { groups: [{ properties: [], rollout_percentage: 10 }] },
                            created_by: {
                                id: 1,
                                uuid: 'user1',
                                distinct_id: 'user1',
                                first_name: 'John',
                                email: 'john@example.com',
                            },
                            created_at: '2023-06-01T00:00:00Z',
                            updated_at: '2023-06-01T00:00:00Z',
                        },
                        {
                            id: '2',
                            name: 'Holdout 2',
                            description: 'Second holdout',
                            filters: { groups: [{ properties: [], rollout_percentage: 20 }] },
                            created_by: {
                                id: 2,
                                uuid: 'user2',
                                distinct_id: 'user2',
                                first_name: 'Jane',
                                email: 'jane@example.com',
                            },
                            created_at: '2023-06-02T00:00:00Z',
                            updated_at: '2023-06-02T00:00:00Z',
                        },
                    ]
                },
                createHoldout: async () => {
                    // Dummy implementation
                    const newHoldout = { ...values.holdout, id: String(Math.random()) }
                    lemonToast.success('Holdout created')
                    return [...values.holdouts, newHoldout]
                },
                updateHoldout: async ({ id, holdout }) => {
                    // Dummy implementation
                    const updatedHoldouts = values.holdouts.map((h) => (h.id === id ? { ...h, ...holdout } : h))
                    lemonToast.success('Holdout updated')
                    return updatedHoldouts
                },
                deleteHoldout: async ({ id }) => {
                    // Dummy implementation
                    const filteredHoldouts = values.holdouts.filter((h) => h.id !== id)
                    lemonToast.success('Holdout deleted')
                    return filteredHoldouts
                },
            },
        ],
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
