import { actions, connect, kea, path, reducers, selectors } from 'kea'
import FuseClass from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'
import type { dashboardsLogicType } from './dashboardsLogicType'
import { userLogic } from 'scenes/userLogic'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectClean } from 'lib/utils'
import { DashboardType } from '~/types'

export enum DashboardsTab {
    Dashboards = 'dashboards',
    Notebooks = 'notebooks',
    Templates = 'templates',
}

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

// Helping kea-typegen navigate the exported default class for Fuse
// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface Fuse extends FuseClass<DashboardType> {}

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
            (s) => [dashboardsModel.selectors.nameSortedDashboards, s.filters, s.fuse],
            (dashboards, filters, fuse) => {
                dashboards = dashboards
                    .filter((d) => !d.deleted)
                    .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
                if (filters.pinned) {
                    dashboards = dashboards.filter((d) => d.pinned)
                } else if (filters.shared) {
                    dashboards = dashboards.filter((d) => d.is_shared)
                } else if (filters.createdBy !== 'All users') {
                    dashboards = dashboards.filter((d) => d.created_by?.uuid === filters.createdBy)
                }
                if (!filters.search) {
                    return dashboards
                }

                return fuse.search(filters.search).map((result: any) => result.item)
            },
        ],

        fuse: [
            () => [dashboardsModel.selectors.nameSortedDashboards],
            (dashboards): Fuse => {
                return new FuseClass<DashboardType>(dashboards, {
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
