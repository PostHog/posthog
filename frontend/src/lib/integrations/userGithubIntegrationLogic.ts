import { actions, events, isBreakpoint, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import type { userGithubIntegrationLogicType } from './userGithubIntegrationLogicType'

const PAGE_SIZE = 500

export interface UserGitHubIntegrationLogicProps {
    installationId: string
}

export const userGithubIntegrationLogic = kea<userGithubIntegrationLogicType>([
    path(['lib', 'integrations', 'userGithubIntegrationLogic']),
    props({} as UserGitHubIntegrationLogicProps),
    key((props) => props.installationId),

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

    listeners(({ actions, values, props: logicProps }) => ({
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
                const response = await api.get(
                    `api/users/@me/integrations/github/${logicProps.installationId}/repos/?limit=${PAGE_SIZE}&offset=${offset}`
                )
                await breakpoint()
                actions.loadRepositoriesPageSuccess(response.repositories, response.has_more)
            } catch (e: any) {
                if (isBreakpoint(e)) {
                    throw e
                }
                actions.loadRepositoriesPageFailure()
            }
        },
    })),

    events(({ actions, props }) => ({
        afterMount: () => {
            if (props.installationId) {
                actions.loadRepositories()
            }
        },
    })),
])
