import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { teamLogic } from 'scenes/teamLogic'

import { Group, GroupTypeIndex } from '~/types'

import type { groupKeySelectLogicType } from './groupKeySelectLogicType'

export interface GroupKeySelectLogicProps {
    groupTypeIndex: GroupTypeIndex
    value: string[]
}

export async function resolveGroupNames(
    teamId: number | null,
    groupTypeIndex: GroupTypeIndex,
    groupKeys: string[]
): Promise<Record<string, string>> {
    if (!teamId || groupKeys.length === 0) {
        return {}
    }
    const results = await Promise.all(
        groupKeys.map(async (groupKey) => {
            try {
                const response = await api.get(
                    `api/environments/${teamId}/groups/find/?${new URLSearchParams({
                        group_type_index: String(groupTypeIndex),
                        group_key: groupKey,
                    }).toString()}`
                )
                return [groupKey, groupDisplayId(response.group_key, response.group_properties)] as const
            } catch {
                return null
            }
        })
    )
    return Object.fromEntries(results.filter((r): r is readonly [string, string] => r !== null))
}

export const groupKeySelectLogic = kea<groupKeySelectLogicType>([
    props({} as GroupKeySelectLogicProps),
    key((props) => `${props.groupTypeIndex}`),
    path((key) => ['lib', 'components', 'PropertyFilters', 'components', 'groupKeySelectLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        setSearchQuery: (query: string) => ({ query }),
        setResolvedNames: (names: Record<string, string>) => ({ names }),
    }),
    reducers({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }: { query: string }) => query,
            },
        ],
        resolvedNames: [
            {} as Record<string, string>,
            {
                setResolvedNames: (state, { names }: { names: Record<string, string> }) => ({ ...state, ...names }),
            },
        ],
    }),
    loaders(({ values, props }) => ({
        groups: [
            [] as Group[],
            {
                loadGroups: async ({ search }: { search?: string }, breakpoint) => {
                    await breakpoint(300)
                    if (!values.currentTeamId) {
                        return []
                    }
                    const params: Record<string, string | number> = {
                        group_type_index: props.groupTypeIndex,
                    }
                    if (search) {
                        params.search = search
                    }
                    const response = await api.get(
                        `api/environments/${values.currentTeamId}/groups/?${new URLSearchParams(
                            Object.entries(params).map(([k, v]) => [k, String(v)])
                        ).toString()}`
                    )
                    breakpoint()
                    return response.results ?? []
                },
            },
        ],
    })),
    selectors({
        groupOptions: [
            (s) => [s.groups],
            (groups: Group[]): { key: string; label: string }[] => {
                return groups.map((g) => ({
                    key: g.group_key,
                    label: groupDisplayId(g.group_key, g.group_properties),
                }))
            },
        ],
    }),
    listeners(({ actions }) => ({
        setSearchQuery: ({ query }: { query: string }) => {
            actions.loadGroups({ search: query })
        },
        loadGroupsSuccess: ({ groups }) => {
            const names: Record<string, string> = {}
            for (const g of groups) {
                names[g.group_key] = groupDisplayId(g.group_key, g.group_properties)
            }
            actions.setResolvedNames(names)
        },
    })),
    afterMount(async ({ actions, props }) => {
        actions.loadGroups({})
        const teamId = teamLogic.findMounted()?.values.currentTeamId ?? null
        const names = await resolveGroupNames(teamId, props.groupTypeIndex, props.value)
        if (Object.keys(names).length > 0) {
            actions.setResolvedNames(names)
        }
    }),
])
