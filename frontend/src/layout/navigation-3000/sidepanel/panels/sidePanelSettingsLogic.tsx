import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { SettingsLogicProps } from 'scenes/settings/types'

import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import type { sidePanelSettingsLogicType } from './sidePanelSettingsLogicType'

export const sidePanelSettingsLogic = kea<sidePanelSettingsLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'panels', 'sidePanelSettingsLogic']),
    connect(() => ({
        values: [sidePanelStateLogic, ['selectedTab', 'sidePanelOpen']],
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    })),

    actions({
        closeSettingsPanel: true,
        openSettingsPanel: (settingsLogicProps: SettingsLogicProps) => ({
            settingsLogicProps,
        }),
        setSettings: (settingsLogicProps: Partial<SettingsLogicProps>) => ({
            settingsLogicProps,
        }),
        setPreviousTab: (tab: SidePanelTab | null) => ({ tab }),
    }),

    reducers(() => ({
        settings: [
            {} as SettingsLogicProps,
            { persist: true },
            {
                openSettingsPanel: (_, { settingsLogicProps }) => {
                    return settingsLogicProps
                },
                setSettings: (state, { settingsLogicProps }) => {
                    return { ...state, ...settingsLogicProps }
                },
                closeSettingsPanel: () => ({}),
            },
        ],
        previousTab: [
            null as SidePanelTab | null,
            {
                setPreviousTab: (_, { tab }) => tab,
                closeSettingsPanel: () => null,
            },
        ],
    })),

    selectors({
        isOpen: [
            (s) => [s.sidePanelOpen, s.selectedTab],
            (sidePanelOpen, selectedTab) => sidePanelOpen && selectedTab === SidePanelTab.Settings,
        ],
    }),

    listeners(({ actions, values }) => ({
        openSettingsPanel: () => {
            // Capture the current tab before switching to settings
            actions.setPreviousTab(values.selectedTab)
            actions.openSidePanel(SidePanelTab.Settings)
        },
        closeSettingsPanel: () => {
            actions.closeSidePanel(SidePanelTab.Settings)
        },
    })),
])
