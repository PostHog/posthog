import { connect, kea, path, selectors } from 'kea'
import { activationLogic } from 'lib/components/ActivationSidebar/activationLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SidePanelTab } from '~/types'

import type { sidePanelLogicType } from './sidePanelLogicType'
import { sidePanelStateLogic } from './sidePanelStateLogic'

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
        ],
    }),

    selectors({
        enabledTabs: [
            (s) => [s.featureFlags, s.isCloudOrDev],
            (featureFlags, isCloudOrDev) => {
                const tabs: SidePanelTab[] = []

                if (featureFlags[FEATURE_FLAGS.NOTEBOOKS]) {
                    tabs.push(SidePanelTab.Notebooks)
                }

                if (isCloudOrDev) {
                    tabs.push(SidePanelTab.Support)
                }

                tabs.push(SidePanelTab.Docs)
                tabs.push(SidePanelTab.Settings)
                tabs.push(SidePanelTab.Activation)

                return tabs
            },
        ],

        visibleTabs: [
            (s) => [
                s.enabledTabs,
                sidePanelStateLogic.selectors.selectedTab,
                sidePanelStateLogic.selectors.sidePanelOpen,
                s.isReady,
                s.hasCompletedAllTasks,
            ],
            (enabledTabs, selectedTab, sidePanelOpen, isReady, hasCompletedAllTasks): SidePanelTab[] => {
                return enabledTabs.filter((tab: any) => {
                    if (tab === selectedTab && sidePanelOpen) {
                        return true
                    }

                    // Hide certain tabs unless they are selected
                    if ([SidePanelTab.Settings].includes(tab)) {
                        return false
                    }

                    if (tab === SidePanelTab.Activation && (!isReady || hasCompletedAllTasks)) {
                        return false
                    }

                    return true
                })
            },
        ],
    }),
])
