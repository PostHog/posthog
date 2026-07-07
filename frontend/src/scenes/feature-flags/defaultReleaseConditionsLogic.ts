import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'

import { FeatureFlagFilters, FeatureFlagGroupType } from '~/types'

import type { defaultReleaseConditionsLogicType } from './defaultReleaseConditionsLogicType'
import { uniformAggregationGroupTypeIndex } from './defaultReleaseConditionsUtils'

export interface DefaultReleaseConditionsResponse {
    enabled: boolean
    default_groups: FeatureFlagGroupType[]
}

export async function fetchDefaultReleaseConditions(teamId: number): Promise<DefaultReleaseConditionsResponse> {
    return await api.get(`/api/environments/${teamId}/default_release_conditions/`)
}

/**
 * Returns the cached value if already loaded, otherwise fetches it directly.
 * Used in loaders that need default release conditions on mount before the
 * async load from defaultReleaseConditionsLogic has resolved.
 */
export async function resolveDefaultReleaseConditions(
    cached: DefaultReleaseConditionsResponse | null,
    teamId: number | undefined
): Promise<DefaultReleaseConditionsResponse | null> {
    if (cached) {
        return cached
    }
    if (!teamId) {
        return null
    }
    try {
        return await fetchDefaultReleaseConditions(teamId)
    } catch (e) {
        console.warn('Failed to fetch default release conditions:', e)
        return null
    }
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
                    return await fetchDefaultReleaseConditions(teamId)
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
                aggregation_group_type_index: uniformAggregationGroupTypeIndex(groups),
            }),
        ],

        hasChanges: [
            (s) => [s.localGroups, s.localEnabled, s.defaultReleaseConditions],
            (localGroups, localEnabled, saved): boolean => {
                if (!saved) {
                    return false
                }
                return localEnabled !== saved.enabled || !objectsEqual(localGroups, saved.default_groups)
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadDefaultReleaseConditions()
    }),
])
