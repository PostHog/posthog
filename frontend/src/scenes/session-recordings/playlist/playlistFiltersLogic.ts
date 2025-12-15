import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import type { playlistFiltersLogicType } from './playlistFiltersLogicType'

export const playlistFiltersLogic = kea<playlistFiltersLogicType>([
    path(['scenes', 'session-recordings', 'playlist', 'playlistFiltersLogic']),
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
        [urls.replay(ReplayTabs.Playlists)]: () => {
            actions.setIsFiltersExpanded(false)
        },
    })),
    actionToUrl(({ values }) => ({
        setIsFiltersExpanded: () => {
            if (values.isFiltersExpanded === false) {
                const newSearchParams = new URLSearchParams(router.values.currentLocation.search)
                newSearchParams.delete('showFilters')
                newSearchParams.delete('filtersTab')
                return [
                    router.values.currentLocation.pathname,
                    newSearchParams.toString(),
                    router.values.currentLocation.hashParams,
                ]
            }
        },
    })),
])
