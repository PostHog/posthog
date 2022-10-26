import { dayjs } from 'lib/dayjs'
import { kea } from 'kea'
import api from 'lib/api'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
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
                const aliveMetrics = ['redis_alive', 'db_alive', 'plugin_sever_alive', 'dead_letter_queue_ratio_ok']
                const aliveSignals = statusMetrics
                    .filter((sm) => sm.key && aliveMetrics.includes(sm.key))
                    .filter((sm) => sm.value).length
                return aliveSignals >= aliveMetrics.length
            },
        ],
        asyncMigrationsOk: [
            () => [systemStatusLogic.selectors.overview, systemStatusLogic.selectors.systemStatusLoading],
            (statusMetrics, systemStatusLoading) => {
                const asyncMigrations = statusMetrics.filter((sm) => sm.key && sm.key == 'async_migrations_ok')[0]
                return systemStatusLoading || !asyncMigrations || asyncMigrations.value
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
    },
    listeners: ({ actions }) => ({
        closeProjectNotice: ({ projectNoticeVariant }) => {
            actions.reportProjectNoticeDismissed(projectNoticeVariant)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLatestVersion()
        },
    }),
})
