import { actions, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import type { githubIntegrationLogicType } from './githubIntegrationLogicType'

const PAGE_SIZE = 500

export const githubIntegrationLogic = kea<githubIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'githubIntegrationLogic', key]),

    actions({
        loadRepositories: true,
        loadRepositoriesPage: (offset: number) => ({ offset }),
        loadRepositoriesPageSuccess: (repositories: GitHubRepoApi[], hasMore: boolean) => ({
            repositories,
            hasMore,
        }),
        loadRepositoriesPageFailure: true,
    }),

    reducers({
        repositories: [
            [] as GitHubRepoApi[],
            {
                loadRepositories: () => [],
                loadRepositoriesPageSuccess: (state, { repositories }) => {
                    const seenIds = new Set(state.map((r) => r.id))
                    const newRepos = repositories.filter((r) => !seenIds.has(r.id))
                    return [...state, ...newRepos]
                },
            },
        ],
        repositoriesLoading: [
            false,
            {
                loadRepositories: () => true,
                loadRepositoriesPageSuccess: (_, { hasMore }) => hasMore,
                loadRepositoriesPageFailure: () => false,
            },
        ],
        currentOffset: [
            0,
            {
                loadRepositories: () => 0,
                loadRepositoriesPageSuccess: (state) => state + PAGE_SIZE,
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadRepositories: () => {
            actions.loadRepositoriesPage(0)
        },
        loadRepositoriesPageSuccess: ({ hasMore }) => {
            if (hasMore) {
                actions.loadRepositoriesPage(values.currentOffset)
            }
        },
        loadRepositoriesPage: async ({ offset }, breakpoint) => {
            try {
                const response = await api.integrations.githubRepositories(props.id, {
                    limit: PAGE_SIZE,
                    offset,
                })
                await breakpoint()
                actions.loadRepositoriesPageSuccess(response.repositories, response.has_more)
            } catch {
                actions.loadRepositoriesPageFailure()
            }
        },
    })),
])
