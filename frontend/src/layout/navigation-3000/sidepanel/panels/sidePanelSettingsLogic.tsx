import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SettingsLogicProps } from 'scenes/settings/types'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import type { sidePanelSettingsLogicType } from './sidePanelSettingsLogicType'

export const sidePanelSettingsLogic = kea<sidePanelSettingsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelSettingsLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    }),

    actions({
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
            },
        ],
    })),

    listeners(({ actions }) => ({
        openSettingsPanel: () => {
            actions.openSidePanel('settings')
        },
    })),
])
