import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { createFuse } from 'lib/utils/fuseSearch'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { WebExperiment } from '~/toolbar/types'

import type { experimentsLogicType } from './experimentsLogicType'

export const experimentsLogic = kea<experimentsLogicType>([
    path(['toolbar', 'experiments', 'experimentsLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ values }) => ({
        allExperiments: [
            [] as WebExperiment[],
            {
                // oxlint-disable-next-line @typescript-eslint/no-unused-vars
                getExperiments: async (_ = null, breakpoint: () => void) => {
                    const url = '/api/projects/@current/web_experiments/'
                    const response = await toolbarFetch(url)

                    let body: unknown = null
                    let parseFailed = false
                    try {
                        body = await response.json()
                    } catch {
                        parseFailed = true
                    }
                    const resultsField = (body as { results?: unknown } | null)?.results

                    if (response.status === 401 || response.status === 403) {
                        // toolbarFetch's no-token short-circuit returns 401 with `{results: []}`
                        // — keep that as a silent empty list rather than re-prompting auth.
                        if (Array.isArray(resultsField)) {
                            return resultsField as WebExperiment[]
                        }
                        toolbarConfigLogic.actions.authenticate()
                        return []
                    }

                    breakpoint()

                    const bodySnippet = parseFailed ? '<non-JSON body>' : JSON.stringify(body ?? null).slice(0, 200)

                    if (!response.ok) {
                        throw new Error(
                            `Error loading experiments: HTTP ${response.status} from ${url} — ${bodySnippet}`
                        )
                    }

                    if (!Array.isArray(resultsField)) {
                        throw new Error(
                            `Error loading experiments: unexpected response shape from ${url} (status ${response.status}) — ${bodySnippet}`
                        )
                    }

                    return resultsField as WebExperiment[]
                },
                updateExperiment: ({ experiment }: { experiment: WebExperiment }) => {
                    return values.allExperiments.filter((r) => r.id !== experiment.id).concat([experiment])
                },
                deleteExperiment: ({ id }: { id: number }) => {
                    return values.allExperiments.filter((r) => r.id !== id)
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
        sortedExperiments: [
            (s) => [s.allExperiments, s.searchTerm],
            (allExperiments, searchTerm) => {
                const filteredExperiments = searchTerm
                    ? createFuse(allExperiments, {
                          keys: ['name'],
                      })
                          .search(searchTerm)
                          .map(({ item }) => item)
                    : allExperiments
                return [...filteredExperiments]
            },
        ],
        experimentCount: [(s) => [s.allExperiments], (allExperiments) => allExperiments.length],
    }),
    permanentlyMount(),
])
