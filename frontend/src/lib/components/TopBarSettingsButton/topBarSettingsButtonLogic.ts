import { connect, kea, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { sceneLogic } from 'scenes/sceneLogic'
import { SettingSectionId } from 'scenes/settings/types'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import type { topBarSettingsButtonLogicType } from './topBarSettingsButtonLogicType'

export const topBarSettingsButtonLogic = kea<topBarSettingsButtonLogicType>([
    path(['layout', 'navigation', 'topBarSettingsButtonLogic']),
    connect(() => ({
        values: [sceneLogic, ['activeLoadedScene'], sidePanelStateLogic, ['sidePanelOpen', 'selectedTab']],
        actions: [sidePanelSettingsLogic, ['openSettingsPanel']],
    })),
    selectors(() => ({
        loadedSceneSettingsSectionId: [
            (s) => [s.activeLoadedScene],
            (activeLoadedScene): SettingSectionId | undefined => activeLoadedScene?.settingSectionId,
        ],
    })),
    subscriptions(({ actions, values }) => ({
        loadedSceneSettingsSectionId: (loadedSceneSettingsSectionId) => {
            // If already open and we detect a change, update the settings panel
            if (loadedSceneSettingsSectionId && values.sidePanelOpen && values.selectedTab === SidePanelTab.Settings) {
                return actions.openSettingsPanel({
                    sectionId: loadedSceneSettingsSectionId,
                })
            }
        },
    })),
])
