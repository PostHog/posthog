import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { defaultEvaluationEnvironmentsLogicType } from './defaultEvaluationEnvironmentsLogicType'

export interface DefaultEvaluationTag {
    id: number
    name: string
}

export interface DefaultEvaluationEnvironmentsResponse {
    default_evaluation_tags: DefaultEvaluationTag[]
    enabled: boolean
}

export const defaultEvaluationEnvironmentsLogic = kea<defaultEvaluationEnvironmentsLogicType>([
    path(['scenes', 'feature-flags', 'defaultEvaluationEnvironmentsLogic']),

    connect({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),

    actions({
        loadDefaultEvaluationEnvironments: true,
        addTag: (tagName: string) => ({ tagName }),
        removeTag: (tagName: string) => ({ tagName }),
        toggleEnabled: (enabled: boolean) => ({ enabled }),
        setNewTagInput: (value: string) => ({ value }),
        setIsAdding: (isAdding: boolean) => ({ isAdding }),
    }),

    reducers({
        newTagInput: [
            '',
            {
                setNewTagInput: (_, { value }) => value,
                addTag: () => '',
            },
        ],
        isAdding: [
            false,
            {
                setIsAdding: (_, { isAdding }) => isAdding,
                addTag: () => false,
            },
        ],
    }),

    loaders(({ values }) => ({
        defaultEvaluationEnvironments: [
            null as DefaultEvaluationEnvironmentsResponse | null,
            {
                loadDefaultEvaluationEnvironments: async () => {
                    const teamId = values.currentTeam?.id
                    if (!teamId) {
                        return null
                    }

                    const response = await api.get(`/api/environments/${teamId}/default_evaluation_tags/`)
                    return response as DefaultEvaluationEnvironmentsResponse
                },

                addTag: async ({ tagName }) => {
                    const teamId = values.currentTeam?.id
                    if (!teamId) {
                        throw new Error('No team selected')
                    }

                    try {
                        const response = await api.create(`/api/environments/${teamId}/default_evaluation_tags/`, {
                            tag_name: tagName,
                        })

                        const currentData = values.defaultEvaluationEnvironments
                        if (!currentData) {
                            return null
                        }

                        // Add the new tag if it was created
                        if (response.created) {
                            return {
                                ...currentData,
                                default_evaluation_tags: [
                                    ...currentData.default_evaluation_tags,
                                    { id: response.id, name: response.name },
                                ],
                            }
                        }

                        return currentData
                    } catch (error: any) {
                        lemonToast.error(error.error || error.detail || 'Failed to add tag')
                        throw error
                    }
                },

                removeTag: async ({ tagName }) => {
                    const teamId = values.currentTeam?.id
                    if (!teamId) {
                        throw new Error('No team selected')
                    }

                    try {
                        await api.delete(
                            `/api/environments/${teamId}/default_evaluation_tags/?tag_name=${encodeURIComponent(tagName)}`
                        )

                        const currentData = values.defaultEvaluationEnvironments
                        if (!currentData) {
                            return null
                        }

                        return {
                            ...currentData,
                            default_evaluation_tags: currentData.default_evaluation_tags.filter(
                                (tag: DefaultEvaluationTag) => tag.name !== tagName
                            ),
                        }
                    } catch (error: any) {
                        lemonToast.error(error.error || error.detail || 'Failed to remove tag')
                        throw error
                    }
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        toggleEnabled: async ({ enabled }) => {
            actions.updateCurrentTeam({
                default_evaluation_environments_enabled: enabled,
            })
        },

        addTagSuccess: () => {
            lemonToast.success('Tag added to default evaluation environments')
        },

        removeTagSuccess: () => {
            lemonToast.success('Tag removed from default evaluation environments')
        },
    })),

    selectors({
        tags: [
            (s) => [s.defaultEvaluationEnvironments],
            (data): DefaultEvaluationTag[] => data?.default_evaluation_tags || [],
        ],

        isEnabled: [(s) => [s.currentTeam], (team): boolean => team?.default_evaluation_environments_enabled || false],

        canAddMoreTags: [(s) => [s.tags], (tags): boolean => tags.length < 10],
    }),

    afterMount(({ actions }) => {
        actions.loadDefaultEvaluationEnvironments()
    }),
])
