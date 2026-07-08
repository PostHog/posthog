import { actions, connect, kea, listeners, path, reducers } from 'kea'
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
        setSceneLayoutConfig: (config: SceneConfig) => ({ config }),
        toggleShowDescription: true,
    }),
    reducers({
        showDescription: [
            true,
            { persist: true },
            {
                toggleShowDescription: (state) => !state,
            },
        ],
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
        sceneLayoutConfig: [
            null as SceneConfig | null,
            {
                setSceneLayoutConfig: (_, { config }) => config,
            },
        ],
    }),
    listeners(({ values }) => ({
        registerScenePanelElement: () => {
            // The memoized selector only recomputes when evaluated, and once the
            // last ScenePanel unmounts nothing subscribes to it — so without this
            // read its cached result keeps the previous (now detached) panel
            // container alive, which pins the departed scene's entire fiber and
            // DOM tree via the element's React fiber expandos.
            void values.scenePanelElement
        },
    })),
])
