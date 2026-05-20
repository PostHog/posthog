import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { SettingsLogicProps } from 'scenes/settings/types'

import { SidePanelTab } from '~/types'

import { sidePanelContextLogic } from '../../sidePanelContextLogic'
import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import type { sidePanelSettingsLogicType } from './sidePanelSettingsLogicType'

export const sidePanelSettingsLogic = kea<sidePanelSettingsLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'panels', 'sidePanelSettingsLogic']),
    connect(() => ({
        values: [
            sidePanelStateLogic,
            ['selectedTab', 'sidePanelOpen'],
            sidePanelContextLogic,
            ['sceneSidePanelContext'],
        ],
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
        /** Whether the current settings were explicitly set via openSettingsPanel.
         *  Stays true while the user remains on the Settings tab so the explicit
         *  section/setting is preserved (and so `sidePanelLogic.enabledTabs` keeps
         *  Settings available on scenes without a `settings_section`). Resets when
         *  the user switches to a different tab or closes the panel. */
        isExplicitSettings: [
            false,
            {
                openSettingsPanel: () => true,
                closeSettingsPanel: () => false,
                closeSidePanel: () => false,
                openSidePanel: (state, { tab }) => (tab === SidePanelTab.Settings ? state : false),
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
        /** When opened from the tab bar, we use the scene's settings_section.
         *  When opened via openSettingsPanel({ sectionId }), the explicit value takes precedence. */
        effectiveSettings: [
            (s) => [s.settings, s.isExplicitSettings, s.sceneSidePanelContext],
            (settings, isExplicitSettings, sceneSidePanelContext): SettingsLogicProps => {
                if (isExplicitSettings) {
                    return settings
                }
                const sceneSection = sceneSidePanelContext?.settings_section
                return sceneSection ? { sectionId: sceneSection } : settings
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        openSettingsPanel: () => {
            actions.setPreviousTab(values.selectedTab)
            actions.openSidePanel(SidePanelTab.Settings)
        },
        closeSettingsPanel: () => {
            actions.closeSidePanel(SidePanelTab.Settings)
        },
    })),
])
