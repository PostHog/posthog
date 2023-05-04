import { actions, connect, kea, path, reducers, selectors } from 'kea'
import Fuse from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'
import type { dashboardsLogicType } from './dashboardsLogicType'
import { userLogic } from 'scenes/userLogic'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectClean } from 'lib/utils'

export enum DashboardsTab {
    Dashboards = 'dashboards',
    Notebooks = 'notebooks',
    Templates = 'templates',
}

export interface DashboardsFilters {
    search: string
    createdBy: number | 'All users'
    pinned: boolean
    shared: boolean
}

export const DEFAULT_FILTERS: DashboardsFilters = {
    search: '',
    createdBy: 'All users',
    pinned: false,
    shared: false,
}

export const dashboardsLogic = kea<dashboardsLogicType>([
    path(['scenes', 'dashboard', 'dashboardsLogic']),
    connect({ values: [userLogic, ['user'], featureFlagLogic, ['featureFlags']] }),
    actions({
        setCurrentTab: (tab: DashboardsTab) => ({ tab }),
        setFilters: (filters: Partial<DashboardsFilters>) => ({
            filters,
        }),
    }),
    reducers({
        currentTab: [
            DashboardsTab.Dashboards as DashboardsTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],

        filters: [
            DEFAULT_FILTERS as DashboardsFilters,
            {
                setFilters: (state, { filters }) =>
                    objectClean({
                        ...(state || {}),
                        ...filters,
                    }),
            },
        ],
    }),

    selectors({
        dashboards: [
            (s) => [dashboardsModel.selectors.nameSortedDashboards, s.filters, s.user, s.fuse],
            (dashboards, filters, user, fuse) => {
                dashboards = dashboards
                    .filter((d) => !d.deleted)
                    .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
                if (filters.pinned) {
                    dashboards = dashboards.filter((d) => d.pinned)
                } else if (filters.shared) {
                    dashboards = dashboards.filter((d) => d.is_shared)
                } else if (filters.createdBy !== 'All users') {
                    dashboards = dashboards.filter((d) => d.created_by && user && d.created_by?.uuid === user.uuid)
                }
                if (!filters.search) {
                    return dashboards
                }

                return fuse.search(filters.search).map((result: any) => result.item)
            },
        ],

        fuse: [
            () => [dashboardsModel.selectors.nameSortedDashboards],
            (dashboards) => {
                return new Fuse(dashboards, {
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
