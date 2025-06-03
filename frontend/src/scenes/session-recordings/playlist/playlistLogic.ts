import { actions, kea, listeners, path, reducers } from 'kea'
import { urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

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
    urlToAction(({ actions }) => ({
        [urls.replay(ReplayTabs.Home)]: (_, searchParams) => {
            if (searchParams.filtersTab && ['filters', 'saved'].includes(searchParams.filtersTab)) {
                actions.setActiveFilterTab(searchParams.filtersTab)
            }
            if (searchParams.showFilters) {
                actions.setIsFiltersExpanded(true)
            }
        },
    })),
    listeners(() => ({
        setIsFiltersExpanded: ({ isFiltersExpanded }) => {
            // If we close the filter modal, we need to remove showFilters & filtersTab params from the url
            if (isFiltersExpanded === false) {
                const currentSearchParams = new URLSearchParams(window.location.search)
                currentSearchParams.delete('showFilters')
                currentSearchParams.delete('filtersTab')
                window.history.replaceState({}, '', `${window.location.pathname}${currentSearchParams.toString() ? '?' + currentSearchParams.toString() : ''}`)
            }
        },
    })),
])
