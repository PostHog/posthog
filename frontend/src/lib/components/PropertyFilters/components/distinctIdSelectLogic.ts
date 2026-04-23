import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { asDisplay } from 'scenes/persons/person-utils'
import { teamLogic } from 'scenes/teamLogic'

import { PersonType } from '~/types'

import type { distinctIdSelectLogicType } from './distinctIdSelectLogicType'

export interface DistinctIdSelectLogicProps {
    value: string[]
}

const PERSON_LOOKUP_LIMIT = 10

export async function resolveDistinctIdNames(distinctIds: string[]): Promise<Record<string, string>> {
    if (distinctIds.length === 0) {
        return {}
    }
    try {
        const personsByDistinctId = await api.persons.getByDistinctIds(distinctIds)
        const names: Record<string, string> = {}
        for (const distinctId of distinctIds) {
            const person = personsByDistinctId[distinctId]
            if (person) {
                names[distinctId] = asDisplay(person)
            }
        }
        return names
    } catch {
        return {}
    }
}

export const distinctIdSelectLogic = kea<distinctIdSelectLogicType>([
    props({} as DistinctIdSelectLogicProps),
    path(['lib', 'components', 'PropertyFilters', 'components', 'distinctIdSelectLogic']),
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
    loaders(({ values }) => ({
        persons: [
            [] as PersonType[],
            {
                loadPersons: async ({ search }: { search?: string }, breakpoint) => {
                    await breakpoint(300)
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await api.persons.list({
                        search: search || undefined,
                        limit: PERSON_LOOKUP_LIMIT,
                    })
                    breakpoint()
                    return response.results ?? []
                },
            },
        ],
    })),
    selectors({
        personOptions: [
            (s) => [s.persons],
            (persons: PersonType[]): { key: string; label: string; person: PersonType }[] => {
                const options: { key: string; label: string; person: PersonType }[] = []
                const seen = new Set<string>()
                for (const person of persons) {
                    // Use the primary distinct_id (first in the list — sorted by is_anonymous_id server-side)
                    const distinctId = person.distinct_ids?.[0]
                    if (!distinctId || seen.has(distinctId)) {
                        continue
                    }
                    seen.add(distinctId)
                    options.push({
                        key: distinctId,
                        label: asDisplay(person),
                        person,
                    })
                }
                return options
            },
        ],
    }),
    listeners(({ actions }) => ({
        setSearchQuery: ({ query }: { query: string }) => {
            actions.loadPersons({ search: query })
        },
        loadPersonsSuccess: ({ persons }) => {
            const names: Record<string, string> = {}
            for (const person of persons) {
                const displayName = asDisplay(person)
                // Map every distinct_id of this person to its display name so selections survive
                // even if the user originally pasted a non-primary distinct_id.
                for (const distinctId of person.distinct_ids ?? []) {
                    names[distinctId] = displayName
                }
            }
            if (Object.keys(names).length > 0) {
                actions.setResolvedNames(names)
            }
        },
    })),
    afterMount(async ({ actions, props }) => {
        actions.loadPersons({})
        const names = await resolveDistinctIdNames(props.value)
        if (Object.keys(names).length > 0) {
            actions.setResolvedNames(names)
        }
    }),
])
