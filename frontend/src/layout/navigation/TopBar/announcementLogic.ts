import { kea, connect, path, actions, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from '../navigationLogic'

import type { announcementLogicType } from './announcementLogicType'

export enum AnnouncementType {
    Demo = 'Demo',
    CloudFlag = 'CloudFlag',
    NewFeature = 'NewFeature',
    AttentionRequired = 'AttentionRequired',
}

// Switch to `false` if we're not showing a feature announcement. Hard-coded because the announcement needs to be manually updated anyways.
const ShowNewFeatureAnnouncement = false
const ShowAttentionRequiredBanner = false

export const announcementLogic = kea<announcementLogicType>([
    path(['layout', 'navigation', 'TopBar', 'announcementLogic']),
    connect({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['preflight'],
            userLogic,
            ['user'],
            navigationLogic,
            ['asyncMigrationsOk'],
            billingLogic,
            ['alertToShow'],
        ],
    }),
    actions({
        hideAnnouncement: (type: AnnouncementType | null) => ({ type }),
        setCanShowAnnouncements: (state: boolean) => ({ state }),
    }),
    reducers({
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
        canShowAnnouncements: [
            true,
            {
                setCanShowAnnouncements: (_, { state }) => state,
            },
        ],
    }),
    selectors({
        closable: [
            (s) => [s.relevantAnnouncementType],
            // The demo announcement is persistent
            (relevantAnnouncementType): boolean => relevantAnnouncementType !== AnnouncementType.Demo,
        ],
        shownAnnouncementType: [
            (s) => [s.relevantAnnouncementType, s.closable, s.closed, s.persistedClosedAnnouncements, s.alertToShow],
            (
                relevantAnnouncementType,
                closable,
                closed,
                persistedClosedAnnouncements,
                alertToShow
            ): AnnouncementType | null => {
                if (
                    (closable &&
                        (closed ||
                            (relevantAnnouncementType && persistedClosedAnnouncements[relevantAnnouncementType]))) ||
                    alertToShow
                ) {
                    return null
                }
                return relevantAnnouncementType
            },
        ],
        relevantAnnouncementType: [
            (s) => [s.canShowAnnouncements, s.cloudAnnouncement, s.preflight, s.user, s.asyncMigrationsOk],
            (canShowAnnouncements, cloudAnnouncement, preflight, user, asyncMigrationsOk): AnnouncementType | null => {
                if (!canShowAnnouncements) {
                    return null
                }
                if (preflight?.demo) {
                    return AnnouncementType.Demo
                } else if (cloudAnnouncement) {
                    return AnnouncementType.CloudFlag
                } else if (
                    ShowAttentionRequiredBanner &&
                    !asyncMigrationsOk &&
                    (user?.is_staff || (user?.organization?.membership_level ?? 0) >= OrganizationMembershipLevel.Admin)
                ) {
                    return AnnouncementType.AttentionRequired
                } else if (ShowNewFeatureAnnouncement) {
                    return AnnouncementType.NewFeature
                }
                return null
            },
        ],
        cloudAnnouncement: [
            (s) => [s.featureFlags],
            (featureFlags): string | null => {
                const flagValue = featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]
                return !!flagValue && typeof flagValue === 'string'
                    ? String(featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]).replace(/_/g, ' ')
                    : null
            },
        ],
    }),
    urlToAction(({ values, actions }) => ({
        '*': ({ pathname }) => {
            if (values.canShowAnnouncements && pathname?.startsWith('/ingestion')) {
                actions.setCanShowAnnouncements(false)
            } else if (!values.canShowAnnouncements) {
                actions.setCanShowAnnouncements(true)
            }
        },
    })),
])
