import { kea, path } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

import type { tagsModelType } from './tagsModelType'

export const tagsModel = kea<tagsModelType>([
    path(['models', 'tagsModel']),
    lazyLoaders(() => ({
        tags: {
            __default: [] as string[],
            loadTags: async () => {
                return (await api.tags.list()) || []
            },
        },
    })),
])
