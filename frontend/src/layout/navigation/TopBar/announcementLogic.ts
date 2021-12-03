import { kea } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { announcementLogicType } from './announcementLogicType'

export enum AnnouncementType {
    CloudFlag = 'CloudFlag',
    GroupAnalytics = 'GroupAnalytics',
}

export const announcementLogic = kea<announcementLogicType<AnnouncementType>>({
    path: ['layout', 'navigation', 'TopBar', 'announcementLogic'],
    connect: {
        values: [featureFlagLogic, ['featureFlags'], groupsAccessLogic, ['showGroupsAnnouncementBanner']],
    },
    actions: {
        hideAnnouncement: (type: AnnouncementType | null) => ({ type }),
    },
    reducers: {
        persistedClosedAnnouncements: [
            {} as Record<AnnouncementType, boolean>,
            { persist: true },
            {
                hideAnnouncement: (state, { type }) => {
                    // :TRICKY: We don't close cloud announcements forever, just until reload
                    if (!type || type === AnnouncementType.CloudFlag) {
                        return state
                    }
                    return { ...state, [type]: true }
                },
            },
        ],
        closed: [
            false,
            {
                hideAnnouncement: () => true,
            },
        ],
    },
    selectors: {
        shownAnnouncementType: [
            (s) => [s.relevantAnnouncementType, s.closed, s.persistedClosedAnnouncements],
            (relevantAnnouncementType, closed, persistedClosedAnnouncements): AnnouncementType | null => {
                if (closed || (relevantAnnouncementType && persistedClosedAnnouncements[relevantAnnouncementType])) {
                    return null
                }
                return relevantAnnouncementType
            },
        ],
        relevantAnnouncementType: [
            (s) => [s.cloudAnnouncement, s.showGroupsAnnouncementBanner],
            (cloudAnnouncement, showGroupsAnnouncementBanner): AnnouncementType | null => {
                if (cloudAnnouncement) {
                    return AnnouncementType.CloudFlag
                } else if (showGroupsAnnouncementBanner) {
                    return AnnouncementType.GroupAnalytics
                }
                return null
            },
        ],
        cloudAnnouncement: [
            (s) => [s.featureFlags],
            (featureFlags): string | null => {
                const flagValue = featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]
                return !!flagValue && typeof flagValue === 'string'
                    ? featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]
                    : null
            },
        ],
    },
})
