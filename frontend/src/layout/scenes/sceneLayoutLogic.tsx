import { actions, connect, kea, path, reducers } from 'kea'
import React from 'react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'
import type { sceneLayoutLogicType } from './sceneLayoutLogicType'

export type SceneLayoutContainerRef = React.RefObject<HTMLElement> | null

export const sceneLayoutLogic = kea<sceneLayoutLogicType>([
    path(['layout', 'scene-layout', 'sceneLayoutLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], panelLayoutLogic, ['mainContentRect']],
    })),
    actions({
        registerScenePanelElement: (element: HTMLElement | null) => ({ element }),
        setScenePanelIsPresent: (active: boolean) => ({ active }),
        setScenePanelOpen: (open: boolean) => ({ open }),
        setForceScenePanelClosedWhenRelative: (closed: boolean) => ({ closed }),
        setSceneLayoutConfig: (config: SceneConfig) => ({ config }),
    }),
    reducers({
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
        scenePanelOpenManual: [
            false,
            {
                setScenePanelOpen: (_, { open }) => open,
            },
        ],
        forceScenePanelClosedWhenRelative: [
            false,
            { persist: true },
            {
                setForceScenePanelClosedWhenRelative: (_, { closed }) => closed,
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
