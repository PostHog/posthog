import { kea } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

import { announcementLogicType } from './announcementLogicType'

export enum AnnouncementType {
    Demo = 'Demo',
    CloudFlag = 'CloudFlag',
    GroupAnalytics = 'GroupAnalytics',
}

export const announcementLogic = kea<announcementLogicType<AnnouncementType>>({
    path: ['layout', 'navigation', 'TopBar', 'announcementLogic'],
    connect: {
        values: [
            featureFlagLogic,
            ['featureFlags'],
            groupsAccessLogic,
            ['showGroupsAnnouncementBanner'],
            preflightLogic,
            ['preflight'],
        ],
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
        closable: [
            (s) => [s.relevantAnnouncementType],
            // The demo announcement is persistent
            (relevantAnnouncementType): boolean => relevantAnnouncementType !== AnnouncementType.Demo,
        ],
        shownAnnouncementType: [
            (s) => [s.relevantAnnouncementType, s.closable, s.closed, s.persistedClosedAnnouncements],
            (relevantAnnouncementType, closable, closed, persistedClosedAnnouncements): AnnouncementType | null => {
                if (
                    closable &&
                    (closed || (relevantAnnouncementType && persistedClosedAnnouncements[relevantAnnouncementType]))
                ) {
                    return null
                }
                return relevantAnnouncementType
            },
        ],
        relevantAnnouncementType: [
            (s) => [s.cloudAnnouncement, s.showGroupsAnnouncementBanner, s.preflight],
            (cloudAnnouncement, showGroupsAnnouncementBanner, preflight): AnnouncementType | null => {
                if (preflight?.demo) {
                    return AnnouncementType.Demo
                } else if (cloudAnnouncement) {
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
