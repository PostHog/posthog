import { connect, kea, path, selectors } from 'kea'

import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { recentItemsMenuLogicType } from './recentItemsMenuLogicType'

const RECENT_ITEMS_LIMIT = 10

export const recentItemsMenuLogic = kea<recentItemsMenuLogicType>([
    path(['layout', 'panel-layout', 'ProjectTree', 'menus', 'recentItemsMenuLogic']),
    connect(() => ({
        values: [recentItemsModel, ['recents as cachedRecents', 'recentsHasLoaded']],
    })),
    selectors({
        recentItems: [
            (s) => [s.cachedRecents],
            (cachedRecents): FileSystemEntry[] => cachedRecents.slice(0, RECENT_ITEMS_LIMIT),
        ],
        recentItemsLoading: [(s) => [s.recentsHasLoaded], (recentsHasLoaded): boolean => !recentsHasLoaded],
    }),
])
