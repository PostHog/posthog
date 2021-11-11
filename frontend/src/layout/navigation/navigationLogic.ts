import { kea } from 'kea'
import api from 'lib/api'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { navigationLogicType } from './navigationLogicType'
import { SystemStatus, VersionType } from '~/types'
import { organizationLogic } from 'scenes/organizationLogic'
import dayjs from 'dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import utc from 'dayjs/plugin/utc'
dayjs.extend(utc)

type WarningType =
    | 'welcome'
    | 'incomplete_setup_on_demo_project'
    | 'incomplete_setup_on_real_project'
    | 'demo_project'
    | 'real_project_with_no_events'
    | null

export const navigationLogic = kea<navigationLogicType<WarningType>>({
    path: ['layout', 'navigation', 'navigationLogic'],
    actions: {
        setMenuCollapsed: (collapsed: boolean) => ({ collapsed }),
        collapseMenu: () => {},
        setSystemStatus: (status: SystemStatus) => ({ status }),
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

                // On cloud non staff users don't have status metrics to review
                const hasNoStatusMetrics = !statusMetrics || statusMetrics.length === 0
                if (hasNoStatusMetrics && preflightLogic.values.preflight?.cloud && !userLogic.values.user?.is_staff) {
                    return true
                }

                // if you have status metrics these three must have `value: true`
                const aliveMetrics = ['redis_alive', 'db_alive', 'plugin_sever_alive']
                const aliveSignals = statusMetrics
                    .filter((sm) => sm.key && aliveMetrics.includes(sm.key))
                    .filter((sm) => sm.value).length
                return aliveSignals >= aliveMetrics.length
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
                return (
                    !latestVersionLoading &&
                    !preflight?.cloud &&
                    latestVersion &&
                    latestVersion !== preflight?.posthog_version
                )
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
                    const versions = (await api.get('https://update.posthog.com')) as VersionType[]
                    for (const version of versions) {
                        if (
                            version?.release_date &&
                            dayjs
                                .utc(version.release_date)
                                .set('hour', 0)
                                .set('minute', 0)
                                .set('second', 0)
                                .set('millisecond', 0) > dayjs()
                        ) {
                            // Release date is in the future
                            continue
                        }
                        return version.version
                    }
                    return null
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
