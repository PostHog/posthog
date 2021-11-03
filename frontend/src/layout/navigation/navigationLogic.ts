import { kea } from 'kea'
import api from 'lib/api'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { navigationLogicType } from './navigationLogicType'
import { SystemStatus } from '~/types'
import { organizationLogic } from 'scenes/organizationLogic'
import dayjs from 'dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

type WarningType =
    | 'welcome'
    | 'incomplete_setup_on_demo_project'
    | 'incomplete_setup_on_real_project'
    | 'demo_project'
    | 'real_project_with_no_events'
    | null

export const navigationLogic = kea<navigationLogicType<WarningType>>({
    actions: {
        setMenuCollapsed: (collapsed: boolean) => ({ collapsed }),
        collapseMenu: () => {},
        setSystemStatus: (status: SystemStatus) => ({ status }),
        setChangelogModalOpen: (isOpen: boolean) => ({ isOpen }),
        setToolbarModalOpen: (isOpen: boolean) => ({ isOpen }),
        setPinnedDashboardsVisible: (visible: boolean) => ({ visible }),
        setInviteMembersModalOpen: (isOpen: boolean) => ({ isOpen }),
        setHotkeyNavigationEngaged: (hotkeyNavigationEngaged: boolean) => ({ hotkeyNavigationEngaged }),
        setProjectModalShown: (isShown: boolean) => ({ isShown }),
        setOrganizationModalShown: (isShown: boolean) => ({ isShown }),
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
        hotkeyNavigationEngaged: [
            false,
            {
                setHotkeyNavigationEngaged: (_, { hotkeyNavigationEngaged }) => hotkeyNavigationEngaged,
            },
        ],
        projectModalShown: [
            false,
            {
                setProjectModalShown: (_, { isShown }) => isShown,
            },
        ],
        organizationModalShown: [
            false,
            {
                setOrganizationModalShown: (_, { isShown }) => isShown,
            },
        ],
    },
    selectors: {
        systemStatus: [
            () => [
                systemStatusLogic.selectors.overview,
                systemStatusLogic.selectors.systemStatusLoading,
                preflightLogic.selectors.siteUrlMisconfigured,
            ],
            (statusMetrics, statusLoading, siteUrlMisconfigured) => {
                if (statusLoading) {
                    return true
                }

                if (siteUrlMisconfigured) {
                    return false
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
            (selectors) => [
                selectors.latestVersion,
                selectors.latestVersionLoading,
                preflightLogic.selectors.preflight,
            ],
            (latestVersion, latestVersionLoading, preflight) => {
                // Always latest version in multitenancy
                return !latestVersionLoading && !preflight?.cloud && latestVersion !== preflight?.posthog_version
            },
        ],
        demoWarning: [
            () => [organizationLogic.selectors.currentOrganization, teamLogic.selectors.currentTeam],
            (organization, currentTeam): WarningType => {
                if (!organization) {
                    return null
                }

                if (
                    organization.setup.is_active &&
                    dayjs(organization.created_at) >= dayjs().subtract(1, 'days') &&
                    currentTeam?.is_demo
                ) {
                    return 'welcome'
                } else if (organization.setup.is_active && currentTeam?.is_demo) {
                    return 'incomplete_setup_on_demo_project'
                } else if (organization.setup.is_active) {
                    return 'incomplete_setup_on_real_project'
                } else if (currentTeam?.is_demo) {
                    return 'demo_project'
                } else if (currentTeam && !currentTeam.ingested_event) {
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
        setHotkeyNavigationEngaged: async ({ hotkeyNavigationEngaged }, breakpoint) => {
            if (hotkeyNavigationEngaged) {
                eventUsageLogic.actions.reportHotkeyNavigation('global', 'g')
                await breakpoint(3000)
                actions.setHotkeyNavigationEngaged(false)
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLatestVersion()
        },
    }),
})
