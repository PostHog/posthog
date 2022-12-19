import { dayjs } from 'lib/dayjs'
import { kea } from 'kea'
import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { VersionType } from '~/types'
import type { navigationLogicType } from './navigationLogicType'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export type ProjectNoticeVariant = 'demo_project' | 'real_project_with_no_events' | 'invite_teammates'

export const navigationLogic = kea<navigationLogicType>({
    path: ['layout', 'navigation', 'navigationLogic'],
    connect: {
        values: [sceneLogic, ['sceneConfig'], membersLogic, ['members', 'membersLoading']],
        actions: [eventUsageLogic, ['reportProjectNoticeDismissed']],
    },
    actions: {
        toggleSideBarBase: true,
        toggleSideBarMobile: true,
        toggleActivationSideBar: true,
        showActivationSideBar: true,
        hideActivationSideBar: true,
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
        openAppSourceEditor: (id: number, pluginId: number) => ({ id, pluginId }),
        closeAppSourceEditor: true,
        setOpenAppMenu: (id: number | null) => ({ id }),
        closeProjectNotice: (projectNoticeVariant: ProjectNoticeVariant) => ({ projectNoticeVariant }),
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
        isActivationSideBarShownBase: [
            false,
            {
                showActivationSideBar: () => true,
                hideActivationSideBar: () => false,
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
        appSourceEditor: [
            null as null | { pluginId: number; id: number },
            {
                openAppSourceEditor: (_, payload) => payload,
                closeAppSourceEditor: () => null,
            },
        ],
        openAppMenu: [null as null | number, { setOpenAppMenu: (_, { id }) => id }],
        projectNoticesAcknowledged: [
            {} as Record<ProjectNoticeVariant, boolean>,
            { persist: true },
            {
                closeProjectNotice: (state, { projectNoticeVariant }) => ({ ...state, [projectNoticeVariant]: true }),
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
        isActivationSideBarShown: [
            (s) => [s.mobileLayout, s.isActivationSideBarShownBase, s.isSideBarShownMobile, s.bareNav],
            (mobileLayout, isActivationSideBarShownBase, isSideBarShownMobile, bareNav) =>
                !bareNav &&
                (mobileLayout ? isActivationSideBarShownBase && !isSideBarShownMobile : isActivationSideBarShownBase),
        ],
        systemStatus: [
            (s) => [s.navigationStatus, preflightLogic.selectors.siteUrlMisconfigured],
            (status, siteUrlMisconfigured) => {
                if (siteUrlMisconfigured) {
                    return false
                }

                // On cloud non staff users don't have status metrics to review
                if (preflightLogic.values.preflight?.cloud && !userLogic.values.user?.is_staff) {
                    return true
                }

                return status.system_status_ok
            },
        ],
        asyncMigrationsOk: [(s) => [s.navigationStatus], (status) => status.async_migrations_ok],
        anyUpdateAvailable: [
            (selectors) => [
                selectors.latestVersion,
                selectors.latestVersionLoading,
                preflightLogic.selectors.preflight,
            ],
            (latestVersion, latestVersionLoading, preflight) => {
                // Always latest version in multitenancy
                if (latestVersionLoading || preflight?.cloud || !latestVersion || !preflight?.posthog_version) {
                    return false
                }
                const [latestMajor, latestMinor, latestPatch] = latestVersion.split('.').map((n) => parseInt(n))
                const [currentMajor, currentMinor, currentPatch] = preflight.posthog_version
                    .split('.')
                    .map((n) => parseInt(n))
                return latestMajor > currentMajor || latestMinor > currentMinor || latestPatch > currentPatch
            },
        ],
        minorUpdateAvailable: [
            (selectors) => [
                selectors.latestVersion,
                selectors.latestVersionLoading,
                preflightLogic.selectors.preflight,
            ],
            (latestVersion, latestVersionLoading, preflight): boolean => {
                // Always latest version in multitenancy
                if (latestVersionLoading || preflight?.cloud || !latestVersion || !preflight?.posthog_version) {
                    return false
                }
                const [latestMajor, latestMinor] = latestVersion.split('.').map((n) => parseInt(n))
                const [currentMajor, currentMinor] = preflight.posthog_version.split('.').map((n) => parseInt(n))
                return latestMajor > currentMajor || latestMinor > currentMinor
            },
        ],
        projectNoticeVariantWithClosability: [
            (s) => [
                organizationLogic.selectors.currentOrganization,
                teamLogic.selectors.currentTeam,
                preflightLogic.selectors.preflight,
                s.members,
                s.membersLoading,
                s.projectNoticesAcknowledged,
            ],
            (
                organization,
                currentTeam,
                preflight,
                members,
                membersLoading,
                projectNoticesAcknowledged
            ): [ProjectNoticeVariant, boolean] | null => {
                if (!organization) {
                    return null
                }

                if (currentTeam?.is_demo && !preflight?.demo) {
                    // If the project is a demo one, show a project-level warning
                    // Don't show this project-level warning in the PostHog demo environemnt though,
                    // as then Announcement is shown instance-wide
                    return ['demo_project', false]
                } else if (
                    !projectNoticesAcknowledged['real_project_with_no_events'] &&
                    currentTeam &&
                    !currentTeam.ingested_event
                ) {
                    return ['real_project_with_no_events', true]
                } else if (!projectNoticesAcknowledged['invite_teammates'] && !membersLoading && members.length <= 1) {
                    return ['invite_teammates', true]
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
        navigationStatus: [
            { system_status_ok: true, async_migrations_ok: true } as {
                system_status_ok: boolean
                async_migrations_ok: boolean
            },
            {
                loadNavigationStatus: async () => {
                    return await api.get('api/instance_settings')
                },
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        closeProjectNotice: ({ projectNoticeVariant }) => {
            actions.reportProjectNoticeDismissed(projectNoticeVariant)
        },
        toggleActivationSideBar: () => {
            if (values.isActivationSideBarShown) {
                actions.hideActivationSideBar()
            } else {
                actions.showActivationSideBar()
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLatestVersion()
        },
    }),
})
