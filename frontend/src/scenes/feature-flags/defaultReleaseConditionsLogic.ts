import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { FeatureFlagFilters, FeatureFlagGroupType } from '~/types'

import type { defaultReleaseConditionsLogicType } from './defaultReleaseConditionsLogicType'

export interface DefaultReleaseConditionsResponse {
    enabled: boolean
    default_groups: FeatureFlagGroupType[]
}

export const defaultReleaseConditionsLogic = kea<defaultReleaseConditionsLogicType>([
    path(['scenes', 'feature-flags', 'defaultReleaseConditionsLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),

    actions({
        setLocalGroups: (groups: FeatureFlagGroupType[]) => ({ groups }),
        setLocalEnabled: (enabled: boolean) => ({ enabled }),
        discardChanges: true,
    }),

    reducers({
        localGroups: [
            null as FeatureFlagGroupType[] | null,
            {
                setLocalGroups: (_, { groups }) => groups,
                loadDefaultReleaseConditionsSuccess: (_, { defaultReleaseConditions }) =>
                    defaultReleaseConditions?.default_groups ?? [],
            },
        ],
        localEnabled: [
            false,
            {
                setLocalEnabled: (_, { enabled }) => enabled,
                loadDefaultReleaseConditionsSuccess: (_, { defaultReleaseConditions }) =>
                    defaultReleaseConditions?.enabled ?? false,
            },
        ],
    }),

    loaders(({ values }) => ({
        defaultReleaseConditions: [
            null as DefaultReleaseConditionsResponse | null,
            {
                loadDefaultReleaseConditions: async () => {
                    const teamId = values.currentTeam?.id
                    if (!teamId) {
                        return null
                    }
                    return (await api.get(
                        `/api/environments/${teamId}/default_release_conditions/`
                    )) as DefaultReleaseConditionsResponse
                },

                saveDefaultReleaseConditions: async () => {
                    const teamId = values.currentTeam?.id
                    if (!teamId) {
                        throw new Error('No team selected')
                    }

                    return (await api.put(`/api/environments/${teamId}/default_release_conditions/`, {
                        enabled: values.localEnabled,
                        default_groups: values.localGroups ?? [],
                    })) as DefaultReleaseConditionsResponse
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        saveDefaultReleaseConditionsSuccess: () => {
            lemonToast.success('Default release conditions saved')
        },
        discardChanges: () => {
            const saved = values.defaultReleaseConditions
            actions.setLocalEnabled(saved?.enabled ?? false)
            actions.setLocalGroups(saved?.default_groups ?? [])
        },
    })),

    selectors({
        isEnabled: [(s) => [s.localEnabled], (enabled): boolean => enabled],

        groups: [(s) => [s.localGroups], (localGroups): FeatureFlagGroupType[] => localGroups ?? []],

        filtersForEditor: [
            (s) => [s.groups],
            (groups): FeatureFlagFilters => ({
                groups: groups.length > 0 ? groups : [{ properties: [], rollout_percentage: 0, variant: null }],
                multivariate: null,
                payloads: {},
            }),
        ],

        hasChanges: [
            (s) => [s.localGroups, s.localEnabled, s.defaultReleaseConditions],
            (localGroups, localEnabled, saved): boolean => {
                if (!saved) {
                    return false
                }
                return (
                    localEnabled !== saved.enabled ||
                    JSON.stringify(localGroups) !== JSON.stringify(saved.default_groups)
                )
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadDefaultReleaseConditions()
    }),
])
