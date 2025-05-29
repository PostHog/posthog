import { actions, kea, path, reducers } from 'kea'

import type { playlistLogicType } from './playlistLogicType'

export const playlistLogic = kea<playlistLogicType>([
    path(['scenes', 'session-recordings', 'playlist', 'playlistLogicType']),
    actions({
        setIsExpanded: (isExpanded: boolean) => ({ isExpanded }), // WIll be removed together with Mix (R.I.P. Mix)
        setIsFiltersExpanded: (isFiltersExpanded: boolean) => ({ isFiltersExpanded }),
        setActiveFilterTab: (activeFilterTab: string) => ({ activeFilterTab }),
    }),
    reducers({
        isExpanded: [
            false,
            {
                setIsExpanded: (_, { isExpanded }) => isExpanded,
            },
        ],
        isFiltersExpanded: [
            false,
            {
                setIsFiltersExpanded: (_, { isFiltersExpanded }) => isFiltersExpanded,
            },
        ],
        activeFilterTab: [
            'filters',
            {
                setActiveFilterTab: (_, { activeFilterTab }) => activeFilterTab,
            },
        ],
    }),
])
