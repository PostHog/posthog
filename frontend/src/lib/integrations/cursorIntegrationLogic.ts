import { kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

export const cursorIntegrationLogic = kea([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'cursorIntegrationLogic', key]),

    loaders(({ props }) => ({
        repositories: [
            [] as { name: string; url: string }[],
            {
                loadRepositories: async () => {
                    let response = await api.integrations.cursorRepositories(props.id)
                    if (response.repositories.length > 0 && response.repositories.every((r) => !r.url)) {
                        response = await api.integrations.cursorRepositories(props.id, {
                            forceRefresh: true,
                        })
                    }
                    return response.repositories
                },
            },
        ],
    })),
])
