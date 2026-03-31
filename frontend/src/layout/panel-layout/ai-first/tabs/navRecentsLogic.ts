import { connect, kea, path, selectors } from 'kea'

import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { navRecentsLogicType } from './navRecentsLogicType'

const NAV_RECENTS_LIMIT = 15

export const navRecentsLogic = kea<navRecentsLogicType>([
    path(['layout', 'panel-layout', 'ai-first', 'tabs', 'navRecentsLogic']),
    connect(() => ({
        values: [recentItemsModel, ['recents as cachedRecents', 'recentsLoading']],
    })),
    selectors({
        recentItems: [
            (s) => [s.cachedRecents],
            (cachedRecents): FileSystemEntry[] => cachedRecents.slice(0, NAV_RECENTS_LIMIT),
        ],
        recentItemsLoading: [(s) => [s.recentsLoading], (recentsLoading): boolean => recentsLoading],
    }),
])
