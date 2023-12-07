import { afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { activationLogic } from 'lib/components/ActivationSidebar/activationLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SidePanelTab } from '~/types'

import { notificationsLogic } from './panels/activity/notificationsLogic'
import type { sidePanelLogicType } from './sidePanelLogicType'
import { sidePanelStateLogic } from './sidePanelStateLogic'

const ALWAYS_EXTRA_TABS = [
    SidePanelTab.Settings,
    SidePanelTab.FeaturePreviews,
    SidePanelTab.Activity,
    SidePanelTab.Welcome,
]

export const sidePanelLogic = kea<sidePanelLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelLogic']),
    connect({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['isCloudOrDev'],
            activationLogic,
            ['isReady', 'hasCompletedAllTasks'],
            sidePanelStateLogic,
            ['selectedTab', 'sidePanelOpen'],
            // We need to mount this to ensure that marking as read works when the panel closes
            notificationsLogic,
            ['unreadCount'],
        ],
        actions: [sidePanelStateLogic, ['closeSidePanel', 'openSidePanel']],
    }),

    reducers(() => ({
        welcomeAnnouncementAcknowledged: [
            false,
            { persist: true },
            {
                closeSidePanel: () => true,
                openSidePanel: () => true,
            },
        ],
    })),
    subscriptions({
        welcomeAnnouncementAcknowledged: (welcomeAnnouncementAcknowledged) => {
            if (welcomeAnnouncementAcknowledged) {
                // Linked to the FF to ensure it isn't shown again
                posthog.capture('3000 welcome acknowledged', {
                    $set: {
                        '3000-welcome-acknowledged': true,
                    },
                })
            }
        },
    }),
    selectors({
        shouldShowWelcomeAnnouncement: [
            (s) => [s.welcomeAnnouncementAcknowledged, s.featureFlags],
            (welcomeAnnouncementAcknowledged, featureFlags) => {
                if (
                    featureFlags[FEATURE_FLAGS.POSTHOG_3000] &&
                    featureFlags[FEATURE_FLAGS.POSTHOG_3000_WELCOME_ANNOUNCEMENT] &&
                    !welcomeAnnouncementAcknowledged
                ) {
                    return true
                }

                return false
            },
        ],

        enabledTabs: [
            (s) => [s.featureFlags, s.isCloudOrDev, s.isReady, s.hasCompletedAllTasks],
            (featureFlags, isCloudOrDev, isReady, hasCompletedAllTasks) => {
                const tabs: SidePanelTab[] = []

                if (featureFlags[FEATURE_FLAGS.NOTEBOOKS]) {
                    tabs.push(SidePanelTab.Notebooks)
                }
                if (isCloudOrDev) {
                    tabs.push(SidePanelTab.Support)
                }
                tabs.push(SidePanelTab.Docs)
                tabs.push(SidePanelTab.Settings)
                if (isReady && !hasCompletedAllTasks) {
                    tabs.push(SidePanelTab.Activation)
                }
                tabs.push(SidePanelTab.Activity)
                if (featureFlags[FEATURE_FLAGS.EARLY_ACCESS_FEATURE_SITE_BUTTON]) {
                    tabs.push(SidePanelTab.FeaturePreviews)
                }
                tabs.push(SidePanelTab.Welcome)

                return tabs
            },
        ],

        visibleTabs: [
            (s) => [s.enabledTabs, s.selectedTab, s.sidePanelOpen, s.isReady, s.hasCompletedAllTasks],
            (enabledTabs, selectedTab, sidePanelOpen): SidePanelTab[] => {
                return enabledTabs.filter((tab: any) => {
                    if (tab === selectedTab && sidePanelOpen) {
                        return true
                    }

                    // Hide certain tabs unless they are selected
                    if (ALWAYS_EXTRA_TABS.includes(tab)) {
                        return false
                    }

                    return true
                })
            },
        ],

        extraTabs: [
            (s) => [s.enabledTabs, s.visibleTabs],
            (enabledTabs, visibleTabs): SidePanelTab[] => {
                return enabledTabs.filter((tab: any) => !visibleTabs.includes(tab))
            },
        ],
    }),

    afterMount(({ values }) => {
        if (values.shouldShowWelcomeAnnouncement) {
            sidePanelStateLogic.findMounted()?.actions.openSidePanel(SidePanelTab.Welcome)
        }
    }),
])
