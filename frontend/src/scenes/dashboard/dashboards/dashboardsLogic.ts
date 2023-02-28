import { kea } from 'kea'
import Fuse from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'
import type { dashboardsLogicType } from './dashboardsLogicType'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export enum DashboardsTab {
    All = 'all',
    Yours = 'yours',
    Pinned = 'pinned',
    Shared = 'shared',
    Templates = 'templates',
}

export const dashboardsLogic = kea<dashboardsLogicType>({
    path: ['scenes', 'dashboard', 'dashboardsLogic'],
    connect: { values: [userLogic, ['user'], featureFlagLogic, ['featureFlags']] },
    actions: {
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setCurrentTab: (tab: DashboardsTab) => ({ tab }),
    },
    reducers: {
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        currentTab: [
            DashboardsTab.All as DashboardsTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    },
    actionToUrl: ({ values }) => ({
        setCurrentTab: () => {
            const tab = values.currentTab === DashboardsTab.All ? undefined : values.currentTab
            if (router.values.searchParams['tab'] === tab) {
                return
            }

            router.actions.push(router.values.location.pathname, { ...router.values.searchParams, tab })
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/dashboard': (_, searchParams) => {
            const tab = searchParams['tab'] || DashboardsTab.All
            if (!values.templatesTabIsVisible && tab === DashboardsTab.Templates) {
                actions.setCurrentTab(DashboardsTab.All)
            } else {
                actions.setCurrentTab(tab)
            }
        },
    }),
    selectors: {
        templatesTabIsVisible: [
            (selectors) => [selectors.user, selectors.featureFlags],
            (user, featureFlags) => {
                return (
                    (!!featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES] && !!user?.is_staff) ||
                    !!featureFlags[FEATURE_FLAGS.TEMPLUKES]
                )
            },
        ],
        dashboards: [
            (selectors) => [
                dashboardsModel.selectors.nameSortedDashboards,
                selectors.searchTerm,
                selectors.currentTab,
                selectors.user,
            ],
            (dashboards, searchTerm, currentTab, user) => {
                dashboards = dashboards
                    .filter((d) => !d.deleted)
                    .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
                if (currentTab === DashboardsTab.Pinned) {
                    dashboards = dashboards.filter((d) => d.pinned)
                } else if (currentTab === DashboardsTab.Shared) {
                    dashboards = dashboards.filter((d) => d.is_shared)
                } else if (currentTab === DashboardsTab.Yours) {
                    dashboards = dashboards.filter((d) => d.created_by && user && d.created_by?.uuid === user.uuid)
                }
                if (!searchTerm) {
                    return dashboards
                }
                return new Fuse(dashboards, {
                    keys: ['key', 'name', 'description', 'tags'],
                    threshold: 0.3,
                })
                    .search(searchTerm)
                    .map((result) => result.item)
            },
        ],
    },
})
