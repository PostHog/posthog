import { actions, connect, kea, path, reducers } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'
import type { sceneLayoutLogicType } from './sceneLayoutLogicType'

export const sceneLayoutLogic = kea<sceneLayoutLogicType>([
    path(['layout', 'scene-layout', 'sceneLayoutLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], panelLayoutLogic, ['mainContentRect']],
    })),
    actions({
        // Legacy actions for portal-based scene panel (when flag is off)
        registerScenePanelElement: (element: HTMLElement | null) => ({ element }),
        setScenePanelIsPresent: (active: boolean) => ({ active }),
        // Common actions
        setScenePanelOpen: (open: boolean) => ({ open }),
        setSceneLayoutConfig: (config: SceneConfig) => ({ config }),
    }),
    reducers({
        // Legacy reducers for portal-based scene panel (when flag is off)
        scenePanelElement: [
            null as HTMLElement | null,
            {
                registerScenePanelElement: (_, { element }) => element,
            },
        ],
        scenePanelIsPresent: [
            false,
            {
                setScenePanelIsPresent: (_, { active }) => active,
            },
        ],
        // Common reducers
        scenePanelOpenManual: [
            false,
            {
                setScenePanelOpen: (_, { open }) => open,
            },
        ],
        sceneLayoutConfig: [
            null as SceneConfig | null,
            {
                setSceneLayoutConfig: (_, { config }) => config,
            },
        ],
    }),
])
