import { kea } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { primaryDashboardModalLogicType } from './primaryDashboardModalLogicType'

export const primaryDashboardModalLogic = kea<primaryDashboardModalLogicType>({
    path: ['scenes', 'project-homepage', 'primaryDashboardModalLogic'],
    connect: {
        actions: [teamLogic, ['updateCurrentTeam']],
        values: [teamLogic, ['currentTeam']],
    },
    actions: {
        showPrimaryDashboardModal: () => true,
        closePrimaryDashboardModal: () => true,
        setPrimaryDashboard: (dashboardId: number) => ({ dashboardId }),
    },
    selectors: {
        primaryDashboardId: [(s) => [s.currentTeam], (currentTeam) => currentTeam?.primary_dashboard],
    },
    reducers: {
        visible: [false, { showPrimaryDashboardModal: () => true, closePrimaryDashboardModal: () => false }],
    },
    listeners: ({ actions }) => ({
        setPrimaryDashboard: async ({ dashboardId }) => {
            actions.updateCurrentTeam({ primary_dashboard: dashboardId })
        },
    }),
})
