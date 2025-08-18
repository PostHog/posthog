import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import React from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { sceneLayoutLogicType } from './sceneLayoutLogicType'

export type SceneLayoutContainerRef = React.RefObject<HTMLElement> | null

// This seems arbitrary, but it's the comfortable width to keep dashboard in a two column layout
const SCENE_WIDTH_WHERE_RELATIVE_PANEL_IS_OPEN = 1358

export const sceneLayoutLogic = kea<sceneLayoutLogicType>([
    path(['layout', 'scene-layout', 'sceneLayoutLogic']),
    connect({ values: [featureFlagLogic, ['featureFlags']] }),
    actions({
        registerScenePanelElement: (element: HTMLElement | null) => ({ element }),
        setScenePanelIsPresent: (active: boolean) => ({ active }),
        setScenePanelOpen: (open: boolean) => ({ open }),
        setForceScenePanelClosedWhenRelative: (closed: boolean) => ({ closed }),
        setSceneContainerRef: (ref: SceneLayoutContainerRef) => ({ ref }),
        setSceneContainerRect: (rect: DOMRect) => ({ rect }),
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
        sceneContainerRef: [
            null as SceneLayoutContainerRef,
            {
                setSceneContainerRef: (_, { ref }) => ref,
            },
        ],
        // Rect might not be the best for our use case right now, but this will be helpful in the future
        sceneContainerRect: [
            null as DOMRect | null,
            {
                setSceneContainerRect: (_, { rect }) => rect,
            },
        ],
    }),
    selectors({
        useSceneTabs: [(s) => [s.featureFlags], (featureFlags) => !!featureFlags[FEATURE_FLAGS.SCENE_TABS]],
        scenePanelIsRelative: [
            (s) => [s.sceneContainerRect],
            (sceneContainerRect) =>
                sceneContainerRect && sceneContainerRect.width >= SCENE_WIDTH_WHERE_RELATIVE_PANEL_IS_OPEN,
        ],
        scenePanelOpen: [
            (s) => [s.scenePanelIsRelative, s.forceScenePanelClosedWhenRelative, s.scenePanelOpenManual],
            (scenePanelIsRelative, forceScenePanelClosedWhenRelative, scenePanelOpenManual) =>
                scenePanelIsRelative ? !forceScenePanelClosedWhenRelative : scenePanelOpenManual,
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        setScenePanelOpen: ({ open }) => {
            // When trying to open a relative panel that's force closed, reset the force closed state
            if (open && values.scenePanelIsRelative && values.forceScenePanelClosedWhenRelative) {
                actions.setForceScenePanelClosedWhenRelative(false)
            }
        },
        setSceneContainerRef: ({ ref }) => {
            // Clean up old ResizeObserver
            if (cache.resizeObserver) {
                cache.resizeObserver.disconnect()
                cache.resizeObserver = null
            }

            // Measure width immediately when container ref is set
            if (ref?.current) {
                actions.setSceneContainerRect(ref.current.getBoundingClientRect())

                // Set up new ResizeObserver for the new container
                if (typeof ResizeObserver !== 'undefined') {
                    cache.resizeObserver = new ResizeObserver(() => {
                        if (ref?.current) {
                            actions.setSceneContainerRect(ref.current.getBoundingClientRect())
                        }
                    })
                    cache.resizeObserver.observe(ref.current)
                }
            }
        },
    })),
    afterMount(({ actions, cache, values }) => {
        const handleResize = (): void => {
            const containerRef = values.sceneContainerRef
            if (containerRef?.current) {
                actions.setSceneContainerRect(containerRef.current.getBoundingClientRect())
            }
        }
        cache.handleResize = handleResize

        // Watch for window resize
        if (typeof window !== 'undefined') {
            window.addEventListener('resize', handleResize)
        }
    }),
    beforeUnmount(({ cache }) => {
        if (typeof window !== 'undefined' && cache.handleResize) {
            window.removeEventListener('resize', cache.handleResize)
        }
        if (cache.resizeObserver) {
            cache.resizeObserver.disconnect()
        }
    }),
])
