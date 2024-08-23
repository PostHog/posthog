import { connect, kea, path, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { AvailableFeature } from '~/types'

import { sidePanelActivityLogic } from './panels/activity/sidePanelActivityLogic'
import { sidePanelStatusLogic } from './panels/sidePanelStatusLogic'
import type { sidePanelLogicType } from './sidePanelLogicType'
import { sidePanelStateLogic, SidePanelTab } from './sidePanelStateLogic'

const ALWAYS_EXTRA_TABS: SidePanelTab[] = ['settings', 'feature-previews', 'activity', 'status', 'exports']

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
            userLogic,
            ['hasAvailableFeature'],
        ],
        actions: [sidePanelStateLogic, ['closeSidePanel', 'openSidePanel']],
    }),

    selectors({
        enabledTabs: [
            (s) => [s.isCloudOrDev, s.isReady, s.hasCompletedAllTasks, s.featureFlags],
            (isCloudOrDev, isReady, hasCompletedAllTasks, featureflags) => {
                const tabs: SidePanelTab[] = []

                tabs.push('notebook')
                tabs.push('docs')
                if (isCloudOrDev) {
                    tabs.push('support')
                }
                tabs.push('activity')
                if (featureflags[FEATURE_FLAGS.DISCUSSIONS]) {
                    tabs.push('discussion')
                }
                if (isReady && !hasCompletedAllTasks) {
                    tabs.push('activation')
                }
                tabs.push('exports')
                tabs.push('feature-previews')
                tabs.push('settings')

                if (isCloudOrDev) {
                    tabs.push('status')
                }

                return tabs
            },
        ],

        visibleTabs: [
            (s) => [s.enabledTabs, s.selectedTab, s.sidePanelOpen, s.unreadCount, s.status, s.hasAvailableFeature],
            (enabledTabs, selectedTab, sidePanelOpen, unreadCount, status, hasAvailableFeature): SidePanelTab[] => {
                return enabledTabs.filter((tab) => {
                    if (tab === selectedTab && sidePanelOpen) {
                        return true
                    }

                    if (tab === 'activity' && unreadCount && hasAvailableFeature(AvailableFeature.AUDIT_LOGS)) {
                        return true
                    }

                    if (tab === 'status' && status !== 'operational') {
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
