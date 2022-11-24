import { afterMount, kea, path } from 'kea'
import api from 'lib/api'

import type { tagsModelType } from './tagsModelType'
import { loaders } from 'kea-loaders'

export const tagsModel = kea<tagsModelType>([
    path(['models', 'tagsModel']),
    loaders(() => ({
        tags: {
            __default: [] as string[],
            loadTags: async () => {
                return (await api.tags.list()) || []
            },
        },
    })),
    afterMount(({ actions }) => actions.loadTags()),
])
