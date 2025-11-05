import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { githubIntegrationLogicType } from './githubIntegrationLogicType'

export const githubIntegrationLogic = kea<githubIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'githubIntegrationLogic', key]),
    actions({
        loadRepositories: () => ({}),
    }),

    loaders(({ props }) => ({
        repositories: [
            [] as string[],
            {
                loadRepositories: async () => {
                    const response = await api.integrations.githubRepositories(props.id)
                    return response.repositories
                },
            },
        ],
    })),
])
