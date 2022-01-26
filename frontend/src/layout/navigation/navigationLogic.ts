import { dayjs } from 'lib/dayjs'
import { kea } from 'kea'
import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { VersionType } from '~/types'
import { navigationLogicType } from './navigationLogicType'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

type WarningType =
    | 'welcome'
    | 'incomplete_setup_on_demo_project'
    | 'incomplete_setup_on_real_project'
    | 'demo_project'
    | 'real_project_with_no_events'
    | 'invite_teammates'
    | null

export const navigationLogic = kea<navigationLogicType<WarningType>>({
    path: ['layout', 'navigation', 'navigationLogic'],
    connect: {
        values: [sceneLogic, ['sceneConfig'], membersLogic, ['members', 'membersLoading']],
    },
    actions: {
        toggleSideBarBase: true,
        toggleSideBarMobile: true,
        hideSideBarMobile: true,
        openSitePopover: true,
        closeSitePopover: true,
        toggleSitePopover: true,
        showCreateOrganizationModal: true,
        hideCreateOrganizationModal: true,
        showCreateProjectModal: true,
        hideCreateProjectModal: true,
        toggleProjectSwitcher: true,
        hideProjectSwitcher: true,
        setHotkeyNavigationEngaged: (hotkeyNavigationEngaged: boolean) => ({ hotkeyNavigationEngaged }),
    },
    reducers: {
        // Non-mobile base
        isSideBarShownBase: [
            true,
            { persist: true },
            {
                toggleSideBarBase: (state) => !state,
            },
        ],
        // Mobile, applied on top of base, so that the sidebar does not show up annoyingly when shrinking the window
        isSideBarShownMobile: [
            false,
            {
                toggleSideBarMobile: (state) => !state,
                hideSideBarMobile: () => false,
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
        mobileLayout: (window) => window.innerWidth < 992, // Sync width threshold with Sass variable $lg!
    }),
    selectors: {
        /** `bareNav` whether the current scene should display a sidebar at all */
        bareNav: [(s) => [s.fullscreen, s.sceneConfig], (fullscreen, sceneConfig) => fullscreen || sceneConfig?.plain],
        isSideBarShown: [
            (s) => [s.mobileLayout, s.isSideBarShownBase, s.isSideBarShownMobile, s.bareNav],
            (mobileLayout, isSideBarShownBase, isSideBarShownMobile, bareNav) =>
                !bareNav && (mobileLayout ? isSideBarShownMobile : isSideBarShownBase),
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
            (s) => [
                organizationLogic.selectors.currentOrganization,
                teamLogic.selectors.currentTeam,
                preflightLogic.selectors.preflight,
                s.members,
                s.membersLoading,
                featureFlagLogic.selectors.featureFlags,
            ],
            (organization, currentTeam, preflight, members, membersLoading, featureFlags): WarningType => {
                if (!organization) {
                    return null
                }

                if (
                    organization.setup.is_active &&
                    dayjs(organization.created_at) >= dayjs().subtract(1, 'days') &&
                    currentTeam?.is_demo
                ) {
                    // TODO: Currently unused
                    return 'welcome'
                } else if (organization.setup.is_active && currentTeam?.is_demo) {
                    // TODO: Currently unused

                    return 'incomplete_setup_on_demo_project'
                } else if (organization.setup.is_active) {
                    // TODO: Currently unused
                    return 'incomplete_setup_on_real_project'
                } else if (currentTeam?.is_demo && !preflight?.demo) {
                    // If the project is a demo one, show a project-level warning
                    // Don't show this project-level warning in the PostHog demo environemnt though,
                    // as then Announcement is shown instance-wide
                    return 'demo_project'
                } else if (currentTeam && !currentTeam.ingested_event) {
                    return 'real_project_with_no_events'
                } else if (
                    featureFlags[FEATURE_FLAGS.INVITE_TEAMMATES_BANNER] == 'test' &&
                    !membersLoading &&
                    members.length <= 1
                ) {
                    return 'invite_teammates'
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
