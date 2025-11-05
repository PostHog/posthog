import { connect, kea, path } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'

import type { tagsModelType } from './tagsModelType'

export const tagsModel = kea<tagsModelType>([
    path(['models', 'tagsModel']),
    connect(() => ({ values: [organizationLogic, ['hasTagging']] })),
    lazyLoaders(({ values }) => ({
        tags: {
            __default: [] as string[],
            loadTags: async () => {
                return values.hasTagging ? (await api.tags.list()) || [] : []
            },
        },
    })),
])
