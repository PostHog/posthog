import Fuse from 'fuse.js'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectClean } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType } from '~/types'

import type { dashboardsLogicType } from './dashboardsLogicType'

export enum DashboardsTab {
    Dashboards = 'dashboards',
    Templates = 'templates',
}

const DEFAULT_SORTING: Sorting = { columnKey: 'name', order: 1 }

export interface DashboardsFilters {
    search: string
    createdBy: string
    pinned: boolean
    shared: boolean
}

export const DEFAULT_FILTERS: DashboardsFilters = {
    search: '',
    createdBy: 'All users',
    pinned: false,
    shared: false,
}

export type DashboardFuse = Fuse<DashboardBasicType> // This is exported for kea-typegen

export const dashboardsLogic = kea<dashboardsLogicType>([
    path(['scenes', 'dashboard', 'dashboardsLogic']),
    connect(() => ({ values: [userLogic, ['user'], featureFlagLogic, ['featureFlags']] })),
    actions({
        setCurrentTab: (tab: DashboardsTab) => ({ tab }),
        setFilters: (filters: Partial<DashboardsFilters>) => ({
            filters,
        }),
        tableSortingChanged: (sorting: Sorting | null) => ({
            sorting,
        }),
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
            DashboardsTab.Dashboards as DashboardsTab,
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
    }),

    selectors({
        isFiltering: [
            (s) => [s.filters],
            (filters) => {
                return Object.keys(filters).some(
                    (key) => filters[key as keyof DashboardsFilters] !== DEFAULT_FILTERS[key]
                )
            },
        ],
        dashboards: [
            (s) => [dashboardsModel.selectors.nameSortedDashboards, s.filters, s.fuse],
            (dashboards, filters, fuse) => {
                let haystack = dashboards
                if (filters.search) {
                    haystack = fuse.search(filters.search).map((result) => result.item)
                }

                if (filters.pinned) {
                    haystack = haystack.filter((d) => d.pinned)
                }
                if (filters.shared) {
                    haystack = haystack.filter((d) => d.is_shared)
                }
                if (filters.createdBy !== 'All users') {
                    haystack = haystack.filter((d) => d.created_by?.uuid === filters.createdBy)
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
    }),
    actionToUrl(({ values }) => ({
        setCurrentTab: () => {
            const tab = values.currentTab === DashboardsTab.Dashboards ? undefined : values.currentTab
            if (router.values.searchParams['tab'] === tab) {
                return
            }

            router.actions.push(router.values.location.pathname, { ...router.values.searchParams, tab })
        },
    })),
    urlToAction(({ actions }) => ({
        '/dashboard': (_, searchParams) => {
            const tab = searchParams['tab'] || DashboardsTab.Dashboards
            actions.setCurrentTab(tab)
        },
    })),
])
