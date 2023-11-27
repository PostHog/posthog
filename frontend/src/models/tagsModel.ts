import { afterMount, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'

import type { tagsModelType } from './tagsModelType'

export const tagsModel = kea<tagsModelType>([
    path(['models', 'tagsModel']),
    connect({ values: [organizationLogic, ['hasDashboardCollaboration']] }),
    loaders(({ values }) => ({
        tags: {
            __default: [] as string[],
            loadTags: async () => {
                return values.hasDashboardCollaboration ? (await api.tags.list()) || [] : []
            },
        },
    })),
    afterMount(({ actions }) => actions.loadTags()),
])
