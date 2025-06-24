import { connect, kea, path, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { AvailableFeature, SidePanelTab } from '~/types'

import { sidePanelActivityLogic } from './panels/activity/sidePanelActivityLogic'
import { sidePanelContextLogic } from './panels/sidePanelContextLogic'
import { sidePanelStatusLogic } from './panels/sidePanelStatusLogic'
import type { sidePanelLogicType } from './sidePanelLogicType'
import { sidePanelStateLogic } from './sidePanelStateLogic'

const ALWAYS_EXTRA_TABS = [SidePanelTab.Settings, SidePanelTab.Activity, SidePanelTab.Status, SidePanelTab.Exports]

export const sidePanelLogic = kea<sidePanelLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['isCloudOrDev'],
            activationLogic,
            ['shouldShowActivationTab'],
            sidePanelStateLogic,
            ['selectedTab', 'sidePanelOpen'],
            // We need to mount this to ensure that marking as read works when the panel closes
            sidePanelActivityLogic,
            ['unreadCount'],
            sidePanelStatusLogic,
            ['status'],
            userLogic,
            ['hasAvailableFeature'],
            sidePanelContextLogic,
            ['sceneSidePanelContext'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [sidePanelStateLogic, ['closeSidePanel', 'openSidePanel']],
    })),

    selectors({
        enabledTabs: [
            (s) => [
                s.selectedTab,
                s.sidePanelOpen,
                s.isCloudOrDev,
                s.featureFlags,
                s.sceneSidePanelContext,
                s.currentTeam,
            ],
            (selectedTab, sidePanelOpen, isCloudOrDev, featureFlags, sceneSidePanelContext, currentTeam) => {
                const tabs: SidePanelTab[] = []

                if (
                    (featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG] &&
                        !featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG]) ||
                    (sidePanelOpen && selectedTab === SidePanelTab.Max)
                ) {
                    // Show Max if user is already enrolled into beta OR they got a link to Max (even if they haven't enrolled)
                    tabs.push(SidePanelTab.Max)
                }
                tabs.push(SidePanelTab.Notebooks)
                tabs.push(SidePanelTab.Docs)
                if (isCloudOrDev) {
                    tabs.push(SidePanelTab.Support)
                }
                tabs.push(SidePanelTab.Activity)

                if (currentTeam?.created_at) {
                    const teamCreatedAt = dayjs(currentTeam.created_at)

                    if (dayjs().diff(teamCreatedAt, 'day') < 30) {
                        tabs.push(SidePanelTab.Activation)
                    }
                }

                tabs.push(SidePanelTab.FeaturePreviews)
                if (featureFlags[FEATURE_FLAGS.DISCUSSIONS]) {
                    tabs.push(SidePanelTab.Discussion)
                }

                if (sceneSidePanelContext.access_control_resource && sceneSidePanelContext.access_control_resource_id) {
                    tabs.push(SidePanelTab.AccessControl)
                }
                tabs.push(SidePanelTab.Exports)
                tabs.push(SidePanelTab.Settings)

                if (isCloudOrDev) {
                    tabs.push(SidePanelTab.Status)
                }

                return tabs
            },
        ],

        visibleTabs: [
            (s) => [
                s.enabledTabs,
                s.selectedTab,
                s.sidePanelOpen,
                s.unreadCount,
                s.status,
                s.hasAvailableFeature,
                s.shouldShowActivationTab,
            ],
            (
                enabledTabs,
                selectedTab,
                sidePanelOpen,
                unreadCount,
                status,
                hasAvailableFeature,
                shouldShowActivationTab
            ): SidePanelTab[] => {
                return enabledTabs.filter((tab) => {
                    if (tab === selectedTab && sidePanelOpen) {
                        return true
                    }

                    if (
                        tab === SidePanelTab.Activity &&
                        unreadCount &&
                        hasAvailableFeature(AvailableFeature.AUDIT_LOGS)
                    ) {
                        return true
                    }

                    if (tab === SidePanelTab.Status && status !== 'operational') {
                        return true
                    }

                    if (tab === SidePanelTab.Activation && !shouldShowActivationTab) {
                        return false
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
