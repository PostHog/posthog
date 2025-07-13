import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SettingsLogicProps } from 'scenes/settings/types'

import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import type { sidePanelSettingsLogicType } from './sidePanelSettingsLogicType'

export const sidePanelSettingsLogic = kea<sidePanelSettingsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelSettingsLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], sidePanelStateLogic, ['selectedTab', 'sidePanelOpen']],
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    })),

    actions({
        closeSettingsPanel: true,
        openSettingsPanel: (settingsLogicProps: SettingsLogicProps) => ({
            settingsLogicProps,
        }),
        setSettings: (settingsLogicProps: SettingsLogicProps) => ({
            settingsLogicProps,
        }),
    }),

    reducers(() => ({
        settings: [
            {} as SettingsLogicProps,
            { persist: true },
            {
                openSettingsPanel: (_, { settingsLogicProps }) => {
                    return settingsLogicProps
                },
                setSettings: (_, { settingsLogicProps }) => {
                    return settingsLogicProps
                },
                closeSettingsPanel: () => ({}),
            },
        ],
    })),

    selectors({
        isOpen: [
            (s) => [s.sidePanelOpen, s.selectedTab],
            (sidePanelOpen, selectedTab) => sidePanelOpen && selectedTab === SidePanelTab.Settings,
        ],
    }),

    listeners(({ actions }) => ({
        openSettingsPanel: () => {
            actions.openSidePanel(SidePanelTab.Settings)
        },
        closeSettingsPanel: () => {
            actions.closeSidePanel(SidePanelTab.Settings)
        },
    })),
])
