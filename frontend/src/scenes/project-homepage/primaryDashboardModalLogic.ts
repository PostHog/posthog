import Fuse from 'fuse.js'
import { kea } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import type { primaryDashboardModalLogicType } from './primaryDashboardModalLogicType'

export const primaryDashboardModalLogic = kea<primaryDashboardModalLogicType>({
    path: ['scenes', 'project-homepage', 'primaryDashboardModalLogic'],
    connect: {
        logic: [eventUsageLogic],
        actions: [teamLogic, ['updateCurrentTeam']],
        values: [teamLogic, ['currentTeam']],
    },
    actions: {
        showPrimaryDashboardModal: () => true,
        closePrimaryDashboardModal: () => true,
        setPrimaryDashboard: (dashboardId: number) => ({ dashboardId }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    },
    selectors: {
        primaryDashboardId: [(s) => [s.currentTeam], (currentTeam) => currentTeam?.primary_dashboard],
        dashboards: [
            (selectors) => [dashboardsModel.selectors.nameSortedDashboards, selectors.searchTerm],
            (dashboards, searchTerm) => {
                dashboards = dashboards
                    .filter((d) => !d.deleted)
                    .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
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
    reducers: {
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        isOpen: [false, { showPrimaryDashboardModal: () => true, closePrimaryDashboardModal: () => false }],
    },
    listeners: ({ actions }) => ({
        setPrimaryDashboard: async ({ dashboardId }) => {
            actions.updateCurrentTeam({ primary_dashboard: dashboardId })
            eventUsageLogic.actions.reportPrimaryDashboardChanged()
        },
        showPrimaryDashboardModal: async () => {
            eventUsageLogic.actions.reportPrimaryDashboardModalOpened()
        },
    }),
})
