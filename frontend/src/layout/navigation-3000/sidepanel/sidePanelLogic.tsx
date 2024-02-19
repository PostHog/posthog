import { connect, kea, path, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { SidePanelTab } from '~/types'

import { sidePanelActivityLogic } from './panels/activity/sidePanelActivityLogic'
import { sidePanelStatusLogic } from './panels/sidePanelStatusLogic'
import type { sidePanelLogicType } from './sidePanelLogicType'
import { sidePanelStateLogic } from './sidePanelStateLogic'

const ALWAYS_EXTRA_TABS = [
    SidePanelTab.Settings,
    SidePanelTab.FeaturePreviews,
    SidePanelTab.Activity,
    SidePanelTab.Status,
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
            sidePanelActivityLogic,
            ['unreadCount'],
            sidePanelStatusLogic,
            ['status'],
        ],
        actions: [sidePanelStateLogic, ['closeSidePanel', 'openSidePanel']],
    }),

    selectors({
        enabledTabs: [
            (s) => [s.isCloudOrDev, s.isReady, s.hasCompletedAllTasks, s.featureFlags],
            (isCloudOrDev, isReady, hasCompletedAllTasks, featureflags) => {
                const tabs: SidePanelTab[] = []

                tabs.push(SidePanelTab.Notebooks)
                tabs.push(SidePanelTab.Docs)
                if (isCloudOrDev) {
                    tabs.push(SidePanelTab.Support)
                }
                tabs.push(SidePanelTab.Activity)
                if (featureflags[FEATURE_FLAGS.DISCUSSIONS]) {
                    tabs.push(SidePanelTab.Discussion)
                }
                if (isReady && !hasCompletedAllTasks) {
                    tabs.push(SidePanelTab.Activation)
                }
                tabs.push(SidePanelTab.FeaturePreviews)
                tabs.push(SidePanelTab.Settings)

                if (isCloudOrDev && featureflags[FEATURE_FLAGS.SIDEPANEL_STATUS]) {
                    tabs.push(SidePanelTab.Status)
                }

                return tabs
            },
        ],

        visibleTabs: [
            (s) => [s.enabledTabs, s.selectedTab, s.sidePanelOpen, s.unreadCount, s.status],
            (enabledTabs, selectedTab, sidePanelOpen, unreadCount, status): SidePanelTab[] => {
                return enabledTabs.filter((tab) => {
                    if (tab === selectedTab && sidePanelOpen) {
                        return true
                    }

                    if (tab === SidePanelTab.Activity && unreadCount) {
                        return true
                    }

                    if (tab === SidePanelTab.Status && status !== 'operational') {
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
])
