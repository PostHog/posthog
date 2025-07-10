import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { GitHubRepoType } from '~/types'

import type { githubIntegrationLogicType } from './githubIntegrationLogicType'

export const githubIntegrationLogic = kea<githubIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'githubIntegrationLogic', key]),
    actions({
        loadAllGitHubRepos: () => ({}),
    }),

    loaders(({ props }) => ({
        githubRepos: [
            [] as GitHubRepoType[],
            {
                loadAllGitHubRepos: async () => {
                    const res = await api.integrations.githubRepos(props.id)
                    return res.teams
                },
            },
        ],
    })),
])
