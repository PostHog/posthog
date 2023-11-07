import { windowValues } from 'kea-window-values'
import { loaders } from 'kea-loaders'
import { kea, path, connect, actions, reducers, selectors, listeners } from 'kea'
import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import type { navigationLogicType } from './navigationLogicType'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'

export type ProjectNoticeVariant =
    | 'demo_project'
    | 'real_project_with_no_events'
    | 'invite_teammates'
    | 'unverified_email'
    | 'is_impersonated'

export const navigationLogic = kea<navigationLogicType>([
    path(['layout', 'navigation', 'navigationLogic']),
    connect({
        values: [sceneLogic, ['sceneConfig', 'activeScene'], membersLogic, ['members', 'membersLoading']],
        actions: [eventUsageLogic, ['reportProjectNoticeDismissed']],
    }),
    actions({
        toggleSideBarBase: (override?: boolean) => ({ override }), // Only use the override for testing
        toggleSideBarMobile: (override?: boolean) => ({ override }), // Only use the override for testing
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
    }),
    loaders({
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
    }),
    windowValues(() => ({
        fullscreen: (window: Window) => !!window.document.fullscreenElement,
        mobileLayout: (window: Window) => window.innerWidth < 992, // Sync width threshold with Sass variable $lg!
    })),
    reducers({
        // Non-mobile base
        isSideBarShownBase: [
            true,
            { persist: true },
            {
                toggleSideBarBase: (state, { override }) => override ?? !state,
            },
        ],
        // Mobile, applied on top of base, so that the sidebar does not show up annoyingly when shrinking the window
        isSideBarShownMobile: [
            false,
            {
                toggleSideBarMobile: (state, { override }) => override ?? !state,
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
    }),
    selectors({
        /** `noSidebar` whether the current scene should display a sidebar at all */
        noSidebar: [
            (s) => [s.fullscreen, s.sceneConfig],
            (fullscreen, sceneConfig) => fullscreen || sceneConfig?.layout === 'plain',
        ],
        minimalTopBar: [
            (s) => [s.activeScene],
            (activeScene) => {
                const minimalTopBarScenes = [Scene.Products, Scene.Onboarding]
                return activeScene && minimalTopBarScenes.includes(activeScene)
            },
        ],
        isSideBarShown: [
            (s) => [s.mobileLayout, s.isSideBarShownBase, s.isSideBarShownMobile, s.noSidebar],
            (mobileLayout, isSideBarShownBase, isSideBarShownMobile, noSidebar) =>
                !noSidebar && (mobileLayout ? isSideBarShownMobile : isSideBarShownBase),
        ],
        isActivationSideBarShown: [
            (s) => [s.mobileLayout, s.isActivationSideBarShownBase, s.isSideBarShownMobile, s.noSidebar],
            (mobileLayout, isActivationSideBarShownBase, isSideBarShownMobile, noSidebar) =>
                !noSidebar &&
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
        projectNoticeVariantWithClosability: [
            (s) => [
                organizationLogic.selectors.currentOrganization,
                teamLogic.selectors.currentTeam,
                preflightLogic.selectors.preflight,
                userLogic.selectors.user,
                s.members,
                s.membersLoading,
                s.projectNoticesAcknowledged,
            ],
            (
                organization,
                currentTeam,
                preflight,
                user,
                members,
                membersLoading,
                projectNoticesAcknowledged
            ): [ProjectNoticeVariant, boolean] | null => {
                if (!organization) {
                    return null
                }
                if (user?.is_impersonated) {
                    return ['is_impersonated', false]
                } else if (currentTeam?.is_demo && !preflight?.demo) {
                    // If the project is a demo one, show a project-level warning
                    // Don't show this project-level warning in the PostHog demo environemnt though,
                    // as then Announcement is shown instance-wide
                    return ['demo_project', false]
                } else if (!user?.is_email_verified && !user?.has_social_auth && preflight?.email_service_available) {
                    return ['unverified_email', false]
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
    }),
    listeners(({ actions, values }) => ({
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
    })),
])
