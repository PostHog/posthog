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
        hideAnnouncement: true,
        openSitePopover: true,
        closeSitePopover: true,
        toggleSitePopover: true,
        showInviteModal: true,
        hideInviteModal: true,
        showCreateOrganizationModal: true,
        hideCreateOrganizationModal: true,
        showChangelogModal: true,
        hideChangelogModal: true,
    },
    reducers: {
        isSideBarShown: [
            true, // TODO: Hide sidebar on mobile by default
            {
                toggleSideBar: (state) => !state,
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
        isChangelogModalShown: [
            false,
            {
                showChangelogModal: () => true,
                hideChangelogModal: () => false,
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
