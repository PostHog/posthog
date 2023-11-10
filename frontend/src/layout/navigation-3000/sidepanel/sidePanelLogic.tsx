import { kea, path, selectors, connect } from 'kea'

import type { sidePanelLogicType } from './sidePanelLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { activationLogic } from 'lib/components/ActivationSidebar/activationLogic'
import { SidePanelTab } from '~/types'

export const sidePanelLogic = kea<sidePanelLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags'], preflightLogic, ['isCloudOrDev']],
    }),

    selectors({
        enabledTabs: [
            (s) => [
                s.featureFlags,
                s.isCloudOrDev,
                // TODO: This is disabled for now until we can solve the circular dependency problem
                activationLogic.selectors.isReady,
                activationLogic.selectors.hasCompletedAllTasks,
            ],
            (featureFlags, isCloudOrDev, activationIsReady, activationHasCompletedAllTasks) => {
                const tabs: SidePanelTab[] = []

                if (featureFlags[FEATURE_FLAGS.NOTEBOOKS]) {
                    tabs.push(SidePanelTab.Notebooks)
                }

                if (isCloudOrDev) {
                    tabs.push(SidePanelTab.Feedback)
                }

                if (featureFlags[FEATURE_FLAGS.SIDE_PANEL_DOCS]) {
                    tabs.push(SidePanelTab.Docs)
                }

                tabs.push(SidePanelTab.Settings)

                if (activationIsReady && !activationHasCompletedAllTasks) {
                    tabs.push(SidePanelTab.Activation)
                }

                return tabs
            },
        ],
    }),
])
