import { actions, kea, reducers, path, listeners, selectors, connect } from 'kea'

import type { sidePanelLogicType } from './sidePanelLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export enum SidePanelTab {
    Notebooks = 'notebook',
    Feedback = 'feedback',
    Docs = 'docs',
}

export const sidePanelLogic = kea<sidePanelLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelLogic']),
    actions({
        setSidePanelOpen: (open: boolean) => ({ open }),
        openSidePanel: (tab: SidePanelTab) => ({ tab }),
        closeSidePanel: (tab?: SidePanelTab) => ({ tab }),
    }),

    connect({
        values: [featureFlagLogic, ['featureFlags'], preflightLogic, ['isCloudOrDev']],
    }),

    reducers(() => ({
        selectedTab: [
            null as SidePanelTab | null,
            { persist: true },
            {
                openSidePanel: (_, { tab }) => tab,
            },
        ],
        sidePanelOpen: [
            false,
            { persist: true },
            {
                setSidePanelOpen: (_, { open }) => open,
            },
        ],
    })),

    selectors({
        enabledTabs: [
            (s) => [s.featureFlags, s.isCloudOrDev],
            (featureFlags, isCloudOrDev) => {
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

                return tabs
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        openSidePanel: () => {
            actions.setSidePanelOpen(true)
        },
        closeSidePanel: ({ tab }) => {
            if (!tab) {
                // If we aren't specifiying the tab we always close
                actions.setSidePanelOpen(false)
            } else if (values.selectedTab === tab) {
                // Otherwise we only close it if the tab is the currently open one
                actions.setSidePanelOpen(false)
            }
        },
    })),
])
