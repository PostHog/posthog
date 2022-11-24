import { kea } from 'kea'
import api from 'lib/api'

import type { tagsModelType } from './tagsModelType'

export const tagsModel = kea<tagsModelType>({
    path: ['models', 'tagsModel'],
    loaders: () => ({
        tags: {
            __default: [] as string[],
            loadTags: async () => {
                return (await api.tags.list()) || []
            },
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => actions.loadTags(),
    }),
})
