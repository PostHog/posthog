import { actions, connect, kea, path, reducers, selectors, listeners, afterMount, beforeUnmount } from 'kea'
import type { sceneLayoutLogicType } from './sceneLayoutLogicType'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React from 'react'
import { sceneLogic } from 'scenes/sceneLogic'

export type SceneLayoutContainerRef = React.RefObject<HTMLElement> | null

// This seems arbitrary, but it's the comfortable width to keep dashboard in a two column layout
const SCENE_WIDTH_WHERE_RELATIVE_PANEL_IS_OPEN = 1358

export const sceneLayoutLogic = kea<sceneLayoutLogicType>([
    path(['layout', 'scene-layout', 'sceneLayoutLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags'], sceneLogic, ['sceneConfig']],
        actions: [sceneLogic, ['setScene']],
    }),
    actions({
        registerScenePanelElement: (element: HTMLElement | null) => ({ element }),
        setScenePanelIsPresent: (active: boolean) => ({ active }),
        setScenePanelOpen: (open: boolean) => ({ open }),
        setSceneWidth: (width: number) => ({ width }),
        setForceScenePanelClosedWhenRelative: (closed: boolean) => ({ closed }),
        setSceneContainerRef: (ref: SceneLayoutContainerRef) => ({ ref }),
        setActiveTab: (tab: 'info' | 'discussions') => ({ tab }),
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
        sceneWidth: [
            0,
            {
                setSceneWidth: (_, { width }) => width,
            },
        ],
        forceScenePanelClosedWhenRelative: [
            false,
            { persist: true },
            {
                setForceScenePanelClosedWhenRelative: (_, { closed }) => closed,
            },
        ],
        sceneContainerRef: [
            null as SceneLayoutContainerRef,
            {
                setSceneContainerRef: (_, { ref }) => ref,
            },
        ],
        activeTab: [
            'info' as 'info' | 'discussions',
            {
                setActiveTab: (_, { tab }) => tab,
                setScene: () => 'info',
                setScenePanelOpen: () => 'info',
                setForceScenePanelClosedWhenRelative: () => 'info',
            },
        ],
    }),
    selectors({
        useSceneTabs: [(s) => [s.featureFlags], (featureFlags) => !!featureFlags[FEATURE_FLAGS.SCENE_TABS]],
        scenePanelIsRelative: [
            (s) => [s.sceneWidth, s.sceneConfig],
            (sceneWidth, sceneConfig) =>
                sceneWidth >= (sceneConfig?.panelOptions?.relativeWidth ?? SCENE_WIDTH_WHERE_RELATIVE_PANEL_IS_OPEN),
        ],
        scenePanelOpen: [
            (s) => [s.scenePanelIsRelative, s.forceScenePanelClosedWhenRelative, s.scenePanelOpenManual],
            (scenePanelIsRelative, forceScenePanelClosedWhenRelative, scenePanelOpenManual) =>
                scenePanelIsRelative ? !forceScenePanelClosedWhenRelative : scenePanelOpenManual,
        ],
    }),
    listeners(({ actions, values }) => ({
        updateSceneWidth: () => {
            const containerRef = values.sceneContainerRef
            if (containerRef?.current) {
                actions.setSceneWidth(containerRef.current.offsetWidth)
            }
        },
        setScenePanelOpen: ({ open }) => {
            // When trying to open a relative panel that's force closed, reset the force closed state
            if (open && values.scenePanelIsRelative && values.forceScenePanelClosedWhenRelative) {
                actions.setForceScenePanelClosedWhenRelative(false)
            }
        },
        setSceneContainerRef: ({ ref }) => {
            // Measure width immediately when container ref is set
            if (ref?.current) {
                actions.setSceneWidth(ref.current.offsetWidth)
            }
        },
    })),
    afterMount(({ actions, cache, values }) => {
        const handleResize = (): void => {
            const containerRef = values.sceneContainerRef
            if (containerRef?.current) {
                actions.setSceneWidth(containerRef.current.offsetWidth)
            }
        }
        cache.handleResize = handleResize

        if (typeof window !== 'undefined') {
            window.addEventListener('resize', handleResize)
        }
    }),
    beforeUnmount(({ cache }) => {
        if (typeof window !== 'undefined' && cache.handleResize) {
            window.removeEventListener('resize', cache.handleResize)
        }
    }),
])
