import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { asDisplay } from 'scenes/persons/person-utils'
import { teamLogic } from 'scenes/teamLogic'

import { PersonType } from '~/types'

import type { distinctIdSelectLogicType } from './distinctIdSelectLogicType'

export interface DistinctIdSelectLogicProps {
    /** Stable per-instance key so two pickers mounted side-by-side don't share state. */
    instanceKey: string
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
    key((props) => props.instanceKey),
    path((k) => ['lib', 'components', 'PropertyFilters', 'components', 'distinctIdSelectLogic', k]),
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
        mergedOptions: [
            (s, p) => [s.persons, s.resolvedNames, p.value],
            (
                persons: PersonType[],
                resolvedNames: Record<string, string>,
                value: string[]
            ): { key: string; label: string }[] => {
                // Emit one option per (person, distinct_id) so the user can see and pick any of
                // a person's identifiers. Flag evaluation matches against the literal distinct_id
                // the SDK passes — picking the right one (or several) matters when a person
                // owns both an anonymous UUID and an identified email-style id.
                const optionMap = new Map<string, { key: string; label: string }>()
                for (const person of persons) {
                    const label = asDisplay(person)
                    for (const distinctId of person.distinct_ids ?? []) {
                        if (!distinctId || optionMap.has(distinctId)) {
                            continue
                        }
                        optionMap.set(distinctId, { key: distinctId, label })
                    }
                }
                // Make sure already-selected distinct_ids stay rendered even when they fall outside
                // the current search results, falling back to a resolved display name when we have one.
                for (const v of value) {
                    if (!optionMap.has(v)) {
                        optionMap.set(v, { key: v, label: resolvedNames[v] ?? v })
                    }
                }
                return Array.from(optionMap.values())
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
