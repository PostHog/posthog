import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { createFuse } from 'lib/utils/fuseSearch'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { ActionType } from '~/types'

import type { actionsLogicType } from './actionsLogicType'

export const actionsLogic = kea<actionsLogicType>([
    path(['toolbar', 'actions', 'actionsLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ values }) => ({
        allActions: [
            [] as ActionType[],
            {
                // oxlint-disable-next-line @typescript-eslint/no-unused-vars
                getActions: async (_ = null, breakpoint: () => void) => {
                    const response = await toolbarFetch('/api/projects/@current/actions/')

                    if (response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                        return []
                    }

                    breakpoint()

                    // Surface the HTTP status (and a truncated body snippet when available)
                    // so error tracking can distinguish auth failures, 5xx outages, and
                    // unexpected response shapes — the previous opaque "Error loading
                    // actions!" message collapsed every failure mode into one fingerprint.
                    if (!response.ok) {
                        const snippet = await response.text().catch(() => '')
                        throw new Error(
                            `Error loading actions! status=${response.status}${
                                snippet ? ` body=${snippet.slice(0, 200)}` : ''
                            }`
                        )
                    }

                    let results: { results?: unknown } | null = null
                    try {
                        results = await response.json()
                    } catch {
                        throw new Error(`Error loading actions! failed to parse response status=${response.status}`)
                    }

                    if (!Array.isArray(results?.results)) {
                        throw new Error(`Error loading actions! unexpected response shape status=${response.status}`)
                    }

                    return results.results
                },
                updateAction: ({ action }: { action: ActionType }) => {
                    return values.allActions.filter((r) => r.id !== action.id).concat([action])
                },
                deleteAction: ({ id }: { id: number }) => {
                    return values.allActions.filter((r) => r.id !== id)
                },
            },
        ],
    })),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    selectors({
        sortedActions: [
            (s) => [s.allActions, s.searchTerm],
            (allActions, searchTerm) => {
                const filteredActions = searchTerm
                    ? createFuse(allActions, {
                          keys: ['name'],
                      })
                          .search(searchTerm)
                          .map(({ item }) => item)
                    : allActions
                return [...filteredActions].sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
            },
        ],
        actionCount: [(s) => [s.allActions], (allActions) => allActions.length],
    }),
    permanentlyMount(),
])
