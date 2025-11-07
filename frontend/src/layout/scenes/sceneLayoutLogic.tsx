import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import React from 'react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'
import type { sceneLayoutLogicType } from './sceneLayoutLogicType'

export type SceneLayoutContainerRef = React.RefObject<HTMLElement> | null

// This seems arbitrary, but it's the comfortable width to keep dashboard in a two column layout
const SCENE_WIDTH_WHERE_RELATIVE_PANEL_IS_OPEN = 1358

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
    selectors({
        scenePanelIsRelative: [
            (s) => [s.mainContentRect],
            (mainContentRect) => mainContentRect && mainContentRect.width >= SCENE_WIDTH_WHERE_RELATIVE_PANEL_IS_OPEN,
        ],
        scenePanelOpen: [
            (s) => [s.scenePanelIsRelative, s.forceScenePanelClosedWhenRelative, s.scenePanelOpenManual],
            (scenePanelIsRelative, forceScenePanelClosedWhenRelative, scenePanelOpenManual) =>
                scenePanelIsRelative ? !forceScenePanelClosedWhenRelative : scenePanelOpenManual,
        ],
    }),
    listeners(({ actions, values }) => ({
        setScenePanelOpen: ({ open }) => {
            // When trying to open a relative panel that's force closed, reset the force closed state
            if (open && values.scenePanelIsRelative && values.forceScenePanelClosedWhenRelative) {
                actions.setForceScenePanelClosedWhenRelative(false)
            }
        },
    })),
])
