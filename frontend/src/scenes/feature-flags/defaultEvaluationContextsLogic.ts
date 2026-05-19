import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { defaultEvaluationContextsLogicType } from './defaultEvaluationContextsLogicType'

export interface DefaultEvaluationContext {
    id: number | string
    name: string
}

export interface DefaultEvaluationContextsResponse {
    default_evaluation_contexts: DefaultEvaluationContext[]
    available_contexts: string[]
    enabled: boolean
}

export const defaultEvaluationContextsLogic = kea<defaultEvaluationContextsLogicType>([
    path(['scenes', 'feature-flags', 'defaultEvaluationContextsLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),

    actions({
        loadDefaultEvaluationContexts: true,
        addContext: (contextName: string) => ({ contextName }),
        removeContext: (contextName: string) => ({ contextName }),
        toggleEnabled: (enabled: boolean) => ({ enabled }),
        setNewContextInput: (value: string) => ({ value }),
        setIsAdding: (isAdding: boolean) => ({ isAdding }),
    }),

    reducers({
        newContextInput: [
            '',
            {
                setNewContextInput: (_, { value }) => value,
                addContext: () => '',
            },
        ],
        isAdding: [
            false,
            {
                setIsAdding: (_, { isAdding }) => isAdding,
                addContext: () => false,
            },
        ],
    }),

    loaders(({ values }) => ({
        defaultEvaluationContexts: [
            null as DefaultEvaluationContextsResponse | null,
            {
                loadDefaultEvaluationContexts: async () => {
                    const teamId = values.currentTeam?.id
                    if (!teamId) {
                        return null
                    }

                    const response = await api.get(`/api/environments/${teamId}/default_evaluation_contexts/`)
                    return response as DefaultEvaluationContextsResponse
                },

                addContext: async ({ contextName }) => {
                    const teamId = values.currentTeam?.id
                    if (!teamId) {
                        throw new Error('No team selected')
                    }

                    try {
                        const response = await api.create(`/api/environments/${teamId}/default_evaluation_contexts/`, {
                            context_name: contextName,
                        })

                        const currentData = values.defaultEvaluationContexts
                        if (!currentData) {
                            return null
                        }

                        if (response.created) {
                            return {
                                ...currentData,
                                default_evaluation_contexts: [
                                    ...currentData.default_evaluation_contexts,
                                    { id: response.id, name: response.name },
                                ],
                                available_contexts: [...currentData.available_contexts, response.name].sort(),
                            }
                        }

                        return currentData
                    } catch (error: any) {
                        lemonToast.error(error.error || error.detail || 'Failed to add context')
                        throw error
                    }
                },

                removeContext: async ({ contextName }) => {
                    const teamId = values.currentTeam?.id
                    if (!teamId) {
                        throw new Error('No team selected')
                    }

                    try {
                        await api.delete(
                            `/api/environments/${teamId}/default_evaluation_contexts/?context_name=${encodeURIComponent(contextName)}`
                        )

                        const currentData = values.defaultEvaluationContexts
                        if (!currentData) {
                            return null
                        }

                        return {
                            ...currentData,
                            default_evaluation_contexts: currentData.default_evaluation_contexts.filter(
                                (ctx: DefaultEvaluationContext) => ctx.name !== contextName
                            ),
                        }
                    } catch (error: any) {
                        lemonToast.error(error.error || error.detail || 'Failed to remove context')
                        throw error
                    }
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        toggleEnabled: async ({ enabled }) => {
            actions.updateCurrentTeam({
                default_evaluation_contexts_enabled: enabled,
            })
        },

        addContextSuccess: () => {
            lemonToast.success('Context added to default evaluation contexts')
        },

        removeContextSuccess: () => {
            lemonToast.success('Context removed from default evaluation contexts')
        },
    })),

    selectors({
        contexts: [
            (s) => [s.defaultEvaluationContexts],
            (data): DefaultEvaluationContext[] => data?.default_evaluation_contexts || [],
        ],

        availableContexts: [(s) => [s.defaultEvaluationContexts], (data): string[] => data?.available_contexts || []],

        isEnabled: [(s) => [s.currentTeam], (team): boolean => team?.default_evaluation_contexts_enabled || false],

        canAddMoreContexts: [(s) => [s.contexts], (contexts): boolean => contexts.length < 10],
    }),

    afterMount(({ actions }) => {
        actions.loadDefaultEvaluationContexts()
    }),
])
