import { kea } from 'kea'
import { FEATURE_FLAGS } from '../../lib/constants'
import { featureFlagLogic } from '../../lib/logic/featureFlagLogic'
import { lemonadeLogicType } from './lemonadeLogicType'

export const lemonadeLogic = kea<lemonadeLogicType>({
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
        showChangelogModal: true,
        hideChangelogModal: true,
        showToolbarModal: true,
        hideToolbarModal: true,
        toggleProjectSwitcher: true,
        hideProjectSwitcher: true,
    },
    reducers: {
        isSideBarShown: [
            window.innerWidth >= 576, // Sync width threshold with Sass variable $sm!
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
        isChangelogModalShown: [
            false,
            {
                showChangelogModal: () => true,
                hideChangelogModal: () => false,
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
