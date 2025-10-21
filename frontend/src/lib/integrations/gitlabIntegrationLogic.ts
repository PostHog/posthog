import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { gitlabIntegrationLogicType } from './gitlabIntegrationLogicType'

export const gitlabIntegrationLogic = kea<gitlabIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'gitlabIntegrationLogic', key]),
    actions({
        loadProjects: () => ({}),
    }),

    loaders(({ props }) => ({
        projects: [
            [] as string[],
            {
                loadProjects: async () => {
                    const response = await api.integrations.gitlabProjects(props.id)
                    return response.projects
                },
            },
        ],
    })),
])
