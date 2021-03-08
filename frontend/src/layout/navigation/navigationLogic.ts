import { kea } from 'kea'
import api from 'lib/api'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { userLogic } from 'scenes/userLogic'
import { navigationLogicType } from './navigationLogicType'
import { OrganizationType, SystemStatus, UserType } from '~/types'
import { organizationLogic } from 'scenes/organizationLogic'
import moment from 'moment'

type WarningType =
    | 'welcome'
    | 'incomplete_setup_on_demo_project'
    | 'incomplete_setup_on_real_project'
    | 'demo_project'
    | 'real_project_with_no_events'
    | null

export const navigationLogic = kea<navigationLogicType<UserType, SystemStatus, WarningType>>({
    actions: {
        setMenuCollapsed: (collapsed: boolean) => ({ collapsed }),
        collapseMenu: () => {},
        setSystemStatus: (status: SystemStatus) => ({ status }),
        setChangelogModalOpen: (isOpen: boolean) => ({ isOpen }),
        updateCurrentOrganization: (id: string) => ({ id }),
        updateCurrentProject: (id: number, dest: string) => ({ id, dest }),
        setToolbarModalOpen: (isOpen: boolean) => ({ isOpen }),
        setPinnedDashboardsVisible: (visible: boolean) => ({ visible }),
        setInviteMembersModalOpen: (isOpen: boolean) => ({ isOpen }),
    },
    reducers: {
        menuCollapsed: [
            typeof window !== 'undefined' && window.innerWidth <= 991,
            {
                setMenuCollapsed: (_, { collapsed }) => collapsed,
            },
        ],
        changelogModalOpen: [
            false,
            {
                setChangelogModalOpen: (_, { isOpen }) => isOpen,
            },
        ],
        toolbarModalOpen: [
            false,
            {
                setToolbarModalOpen: (_, { isOpen }) => isOpen,
            },
        ],
        inviteMembersModalOpen: [
            false,
            {
                setInviteMembersModalOpen: (_, { isOpen }) => isOpen,
            },
        ],
        pinnedDashboardsVisible: [
            false,
            {
                setPinnedDashboardsVisible: (_, { visible }) => visible,
            },
        ],
    },
    selectors: {
        systemStatus: [
            () => [systemStatusLogic.selectors.systemStatus, systemStatusLogic.selectors.systemStatusLoading],
            (statusMetrics, statusLoading) => {
                if (statusLoading) {
                    return true
                }
                const aliveMetrics = ['redis_alive', 'db_alive', 'plugin_sever_alive']
                let aliveSignals = 0
                for (const metric of statusMetrics) {
                    if (metric.key && aliveMetrics.includes(metric.key) && metric.value) {
                        aliveSignals = aliveSignals + 1
                    }
                    if (aliveSignals >= aliveMetrics.length) {
                        return true
                    }
                }
                return false
            },
        ],
        updateAvailable: [
            (selectors) => [selectors.latestVersion, selectors.latestVersionLoading, userLogic.selectors.user],
            (latestVersion, latestVersionLoading, user) => {
                // Always latest version in multitenancy
                return !latestVersionLoading && !user?.is_multi_tenancy && latestVersion !== user?.posthog_version
            },
        ],
        currentTeam: [
            () => [userLogic.selectors.user],
            (user) => {
                return user?.team?.id
            },
        ],
        demoWarning: [
            () => [userLogic.selectors.user, organizationLogic.selectors.currentOrganization],
            (user: UserType, organization: OrganizationType): WarningType => {
                if (
                    organization.setup.is_active &&
                    moment(organization.created_at) >= moment().subtract(1, 'days') &&
                    user.team?.is_demo
                ) {
                    return 'welcome'
                } else if (organization.setup.is_active && user.team?.is_demo) {
                    return 'incomplete_setup_on_demo_project'
                } else if (organization.setup.is_active) {
                    return 'incomplete_setup_on_real_project'
                } else if (user.team?.is_demo) {
                    return 'demo_project'
                } else if (user.team && !user.team.ingested_event) {
                    return 'real_project_with_no_events'
                }
                return null
            },
        ],
    },
    loaders: {
        latestVersion: [
            null as string | null,
            {
                loadLatestVersion: async () => {
                    const versions = await api.get('https://update.posthog.com/versions')
                    return versions[0].version
                },
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        collapseMenu: () => {
            if (!values.menuCollapsed && window.innerWidth <= 991) {
                actions.setMenuCollapsed(true)
            }
        },
        updateCurrentOrganization: async ({ id }) => {
            await api.update('api/user', {
                user: { current_organization_id: id },
            })
            location.href = '/'
        },
        updateCurrentProject: async ({ id, dest }) => {
            if (values.currentTeam === id) {
                return
            }
            await api.update('api/user', {
                user: { current_team_id: id },
            })
            location.href = dest
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLatestVersion()
        },
    }),
})
