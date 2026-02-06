import Fuse from 'fuse.js'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { objectClean } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { tagsModel } from '~/models/tagsModel'
import { ActivityScope, Breadcrumb, DashboardBasicType } from '~/types'

import type { dashboardsLogicType } from './dashboardsLogicType'

export enum DashboardsTab {
    All = 'all',
    Yours = 'yours',
    Pinned = 'pinned',
    Templates = 'templates',
}

const DEFAULT_SORTING: Sorting = { columnKey: 'name', order: 1 }

export interface DashboardsFilters {
    search: string
    createdBy: string
    pinned: boolean
    shared: boolean
    tags?: string[]
}

export const DEFAULT_FILTERS: DashboardsFilters = {
    search: '',
    createdBy: 'All users',
    pinned: false,
    shared: false,
    tags: [],
}

export type DashboardFuse = Fuse<DashboardBasicType> // This is exported for kea-typegen

export const dashboardsLogic = kea<dashboardsLogicType>([
    path(['scenes', 'dashboard', 'dashboardsLogic']),
    tabAwareScene(),
    connect(() => ({
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags'], tagsModel, ['tags']],
    })),
    actions({
        setCurrentTab: (tab: DashboardsTab) => ({ tab }),
        setFilters: (filters: Partial<DashboardsFilters>) => ({
            filters,
        }),
        tableSortingChanged: (sorting: Sorting | null) => ({
            sorting,
        }),
        setTagSearch: (search: string) => ({ search }),
        setShowTagPopover: (visible: boolean) => ({ visible }),
    }),
    reducers({
        tableSorting: [
            DEFAULT_SORTING,
            { persist: true },
            {
                tableSortingChanged: (_, { sorting }) => sorting || DEFAULT_SORTING,
            },
        ],
        currentTab: [
            DashboardsTab.All as DashboardsTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],

        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) =>
                    objectClean({
                        ...state,
                        ...filters,
                    }),
            },
        ],
        tagSearch: [
            '',
            {
                setTagSearch: (_, { search }) => search,
                setShowTagPopover: (state, { visible }) => (visible ? state : ''),
            },
        ],
        showTagPopover: [
            false,
            {
                setShowTagPopover: (_, { visible }) => visible,
            },
        ],
    }),

    selectors({
        isFiltering: [
            (s) => [s.filters],
            (filters) => {
                return Object.keys(filters).some((key) => {
                    const filterKey = key as keyof DashboardsFilters
                    return filters[filterKey] !== DEFAULT_FILTERS[filterKey]
                })
            },
        ],
        filteredTags: [
            (s) => [s.tags, s.tagSearch],
            (tags, search) => {
                if (!search) {
                    return tags || []
                }
                return (tags || []).filter((tag) => tag.toLowerCase().includes(search.toLowerCase()))
            },
        ],
        dashboards: [
            (s) => [dashboardsModel.selectors.nameSortedDashboards, s.filters, s.fuse, s.currentTab, s.user],
            (dashboards, filters, fuse, currentTab, user) => {
                let haystack = dashboards
                if (filters.search) {
                    haystack = fuse.search(filters.search).map((result) => result.item)
                }
                if (currentTab === DashboardsTab.Pinned) {
                    haystack = haystack.filter((d) => d.pinned)
                }
                if (filters.pinned) {
                    haystack = haystack.filter((d) => d.pinned)
                }
                if (filters.shared) {
                    haystack = haystack.filter((d) => d.is_shared)
                }
                if (currentTab === DashboardsTab.Yours) {
                    haystack = haystack.filter((d) => d.created_by?.uuid === user?.uuid)
                } else if (filters.createdBy !== 'All users') {
                    haystack = haystack.filter((d) => d.created_by?.uuid === filters.createdBy)
                }
                if (filters.tags && filters.tags.length > 0) {
                    haystack = haystack.filter((d) => filters.tags?.some((tag) => d.tags?.includes(tag)))
                }
                return haystack
            },
        ],

        fuse: [
            () => [dashboardsModel.selectors.nameSortedDashboards],
            (dashboards): DashboardFuse => {
                return new Fuse<DashboardBasicType>(dashboards, {
                    keys: ['key', 'name', 'description', 'tags'],
                    threshold: 0.3,
                })
            },
        ],

        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'dashboards',
                    name: 'Dashboards',
                    iconType: 'dashboard',
                },
            ],
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.DASHBOARD,
            }),
        ],
    }),
    tabAwareActionToUrl(({ values }) => ({
        setCurrentTab: () => {
            const tab = values.currentTab === DashboardsTab.All ? undefined : values.currentTab
            if (router.values.searchParams['tab'] === tab) {
                return
            }

            router.actions.push(router.values.location.pathname, { ...router.values.searchParams, tab })
        },
    })),
    tabAwareUrlToAction(({ actions }) => ({
        '/dashboard': (_, searchParams) => {
            const tab = searchParams['tab'] || DashboardsTab.All
            actions.setCurrentTab(tab)
        },
    })),
])
