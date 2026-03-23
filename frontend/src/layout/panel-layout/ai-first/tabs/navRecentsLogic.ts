import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { navRecentsLogicType } from './navRecentsLogicType'

const NAV_RECENTS_LIMIT = 15
const RECENTS_POLL_INTERVAL_MS = 30000

export const navRecentsLogic = kea<navRecentsLogicType>([
    path(['layout', 'panel-layout', 'ai-first', 'tabs', 'navRecentsLogic']),
    loaders({
        recentItems: [
            [] as FileSystemEntry[],
            {
                loadRecentItems: async (_, breakpoint) => {
                    const response = await api.fileSystem.list({
                        orderBy: '-last_viewed_at',
                        notType: 'folder',
                        limit: NAV_RECENTS_LIMIT,
                    })
                    breakpoint()
                    return response.results
                },
            },
        ],
    }),
    afterMount(({ actions, cache }) => {
        actions.loadRecentItems({})
        cache.disposables.add(() => {
            const pollInterval = setInterval(() => {
                if (document.visibilityState === 'visible') {
                    actions.loadRecentItems({})
                }
            }, RECENTS_POLL_INTERVAL_MS)
            return () => clearInterval(pollInterval)
        }, 'recentsPoll')
    }),
])
