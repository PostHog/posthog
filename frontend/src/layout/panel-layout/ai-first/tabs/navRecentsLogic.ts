import { connect, kea, path, selectors } from 'kea'

import { FileSystemEntry } from '@posthog/query-frontend/schema/schema-general'

import { recentItemsModel } from '~/models/recentItemsModel'

import type { navRecentsLogicType } from './navRecentsLogicType'

const NAV_RECENTS_LIMIT = 15

export const navRecentsLogic = kea<navRecentsLogicType>([
    path(['layout', 'panel-layout', 'ai-first', 'tabs', 'navRecentsLogic']),
    connect(() => ({
        values: [recentItemsModel, ['recents as cachedRecents', 'recentsHasLoaded']],
    })),
    selectors({
        recentItems: [
            (s) => [s.cachedRecents],
            (cachedRecents): FileSystemEntry[] => cachedRecents.slice(0, NAV_RECENTS_LIMIT),
        ],
        recentItemsLoading: [(s) => [s.recentsHasLoaded], (recentsHasLoaded): boolean => !recentsHasLoaded],
    }),
])
