import { connect, kea, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { SettingSectionId } from 'scenes/settings/types'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import type { topBarSettingsButtonLogicType } from './topBarSettingsButtonLogicType'

export const topBarSettingsButtonLogic = kea<topBarSettingsButtonLogicType>([
    path(['layout', 'navigation', 'topBarSettingsButtonLogic']),
    connect(() => ({
        values: [
            sceneLogic,
            ['activeLoadedScene'],
            sidePanelStateLogic,
            ['sidePanelOpen', 'selectedTab'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [sidePanelSettingsLogic, ['openSettingsPanel']],
    })),
    selectors(() => ({
        loadedSceneSettingsSectionId: [
            (s) => [s.activeLoadedScene, s.featureFlags],
            (activeLoadedScene, featureFlags): SettingSectionId | undefined => {
                const settingSectionId = activeLoadedScene?.settingSectionId

                // Only show CRM settings button when the feature flag is enabled
                if (settingSectionId === 'environment-crm' && !featureFlags[FEATURE_FLAGS.CRM_ITERATION_ONE]) {
                    return undefined
                }

                return settingSectionId
            },
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
