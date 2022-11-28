import { afterMount, connect, kea, path } from 'kea'
import api from 'lib/api'

import type { tagsModelType } from './tagsModelType'
import { loaders } from 'kea-loaders'
import { organizationLogic } from 'scenes/organizationLogic'

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
