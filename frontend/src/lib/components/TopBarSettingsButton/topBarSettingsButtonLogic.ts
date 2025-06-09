import { connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { SettingSectionId } from 'scenes/settings/types'

import type { topBarSettingsButtonLogicType } from './topBarSettingsButtonLogicType'

export const topBarSettingsButtonLogic = kea<topBarSettingsButtonLogicType>([
    path(['layout', 'navigation', 'topBarSettingsButtonLogic']),
    connect(() => ({
        values: [sceneLogic, ['activeLoadedScene']],
    })),
    selectors(() => ({
        loadedSceneSettingsSectionId: [
            (s) => [s.activeLoadedScene],
            (activeLoadedScene): SettingSectionId | undefined => activeLoadedScene?.settingSectionId,
        ],
    })),
])
