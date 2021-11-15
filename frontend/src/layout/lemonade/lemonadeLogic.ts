import { kea } from 'kea'
import { FEATURE_FLAGS } from '../../lib/constants'
import { featureFlagLogic } from '../../lib/logic/featureFlagLogic'
import { lemonadeLogicType } from './lemonadeLogicType'

export const lemonadeLogic = kea<lemonadeLogicType>({
    path: ['layout', 'lemonade', 'lemonadeLogic'],
    connect: {
        values: [featureFlagLogic, ['featureFlags']],
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
    },
    selectors: {
        isSideBarForciblyHidden: [() => [() => document.fullscreenElement], (fullscreenElement) => !!fullscreenElement],
        isSideBarShown: [
            (s) => [s.isSideBarShownRaw, s.isSideBarForciblyHidden],
            (isSideBarShownRaw, isSideBarForciblyHidden) => isSideBarShownRaw && !isSideBarForciblyHidden,
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
    },
})
