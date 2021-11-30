import dayjs from 'dayjs'
import { kea } from 'kea'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { VersionType } from '~/types'
import { navigationLogicType } from './navigationLogicType'

type WarningType =
    | 'welcome'
    | 'incomplete_setup_on_demo_project'
    | 'incomplete_setup_on_real_project'
    | 'demo_project'
    | 'real_project_with_no_events'
    | null

export const navigationLogic = kea<navigationLogicType<WarningType>>({
    path: ['layout', 'navigation', 'navigationLogic'],
    connect: {
        values: [featureFlagLogic, ['featureFlags'], sceneLogic, ['sceneConfig']],
    },
    actions: {
        toggleSideBar: true,
        hideSideBar: true,
        hideAnnouncement: true,
        openSitePopover: true,
        closeSitePopover: true,
        toggleSitePopover: true,
        showInviteModal: true,
        hideInviteModal: true,
        showCreateOrganizationModal: true,
        hideCreateOrganizationModal: true,
        showCreateProjectModal: true,
        hideCreateProjectModal: true,
        showToolbarModal: true,
        hideToolbarModal: true,
        toggleProjectSwitcher: true,
        hideProjectSwitcher: true,
        setHotkeyNavigationEngaged: (hotkeyNavigationEngaged: boolean) => ({ hotkeyNavigationEngaged }),
    },
    reducers: {
        isSideBarShownRaw: [
            window.innerWidth >= 992, // Sync width threshold with Sass variable $lg!
            {
                toggleSideBar: (state) => !state,
                hideSideBar: () => false,
            },
        ],
        isAnnouncementShown: [
            true,
            {
                hideAnnouncement: () => false,
            },
        ],
        isSitePopoverOpen: [
            false,
            {
                openSitePopover: () => true,
                closeSitePopover: () => false,
                toggleSitePopover: (state) => !state,
            },
        ],
        isInviteModalShown: [
            false,
            {
                showInviteModal: () => true,
                hideInviteModal: () => false,
            },
        ],
        isCreateOrganizationModalShown: [
            false,
            {
                showCreateOrganizationModal: () => true,
                hideCreateOrganizationModal: () => false,
            },
        ],
        isCreateProjectModalShown: [
            false,
            {
                showCreateProjectModal: () => true,
                hideCreateProjectModal: () => false,
            },
        ],
        isToolbarModalShown: [
            false,
            {
                showToolbarModal: () => true,
                hideToolbarModal: () => false,
            },
        ],
        isProjectSwitcherShown: [
            false,
            {
                toggleProjectSwitcher: (state) => !state,
                hideProjectSwitcher: () => false,
            },
        ],
        hotkeyNavigationEngaged: [
            false,
            {
                setHotkeyNavigationEngaged: (_, { hotkeyNavigationEngaged }) => hotkeyNavigationEngaged,
            },
        ],
    },
    windowValues: () => ({
        fullscreen: (window) => !!window.document.fullscreenElement,
    }),
    selectors: {
        /** `bareNav` whether the current scene should display a sidebar at all */
        bareNav: [(s) => [s.fullscreen, s.sceneConfig], (fullscreen, sceneConfig) => fullscreen || sceneConfig?.plain],
        isSideBarShown: [
            (s) => [s.isSideBarShownRaw, s.bareNav],
            (isSideBarShownRaw, bareNav) => isSideBarShownRaw && !bareNav,
        ],
        announcementMessage: [
            (s) => [s.featureFlags],
            (featureFlags): string | null => {
                const flagValue = featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]
                return flagValue && typeof flagValue === 'string'
                    ? featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]
                    : null
            },
        ],
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
    listeners: ({ actions }) => ({
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
