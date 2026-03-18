import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { recentItemsMenuLogicType } from './recentItemsMenuLogicType'

const RECENT_ITEMS_LIMIT = 10

export const recentItemsMenuLogic = kea<recentItemsMenuLogicType>([
    path(['layout', 'panel-layout', 'ProjectTree', 'menus', 'recentItemsMenuLogic']),
    loaders({
        recentItems: [
            [] as FileSystemEntry[],
            {
                loadRecentItems: async (_, breakpoint) => {
                    const response = await api.fileSystem.list({
                        orderBy: '-last_viewed_at',
                        notType: 'folder',
                        limit: RECENT_ITEMS_LIMIT,
                    })
                    breakpoint()
                    return response.results
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadRecentItems({})
    }),
])
