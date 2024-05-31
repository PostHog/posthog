import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { windowValues } from 'kea-window-values'
import { PostHogAppToolbarEvent } from 'lib/components/heatmaps/utils'
import { HedgehogActor } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { SPRITE_SIZE } from 'lib/components/HedgehogBuddy/sprites/sprites'

import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { inBounds, TOOLBAR_ID } from '~/toolbar/utils'

import type { toolbarLogicType } from './toolbarLogicType'

const MARGIN = 2

export type MenuState = 'none' | 'heatmap' | 'actions' | 'flags' | 'inspect' | 'hedgehog' | 'debugger'

export const toolbarLogic = kea<toolbarLogicType>([
    path(['toolbar', 'bar', 'toolbarLogic']),
    connect(() => ({
        actions: [
            actionsTabLogic,
            ['showButtonActions', 'hideButtonActions', 'selectAction'],
            elementsLogic,
            ['enableInspect', 'disableInspect', 'createAction'],
            heatmapLogic,
            [
                'enableHeatmap',
                'disableHeatmap',
                'patchHeatmapFilters',
                'setHeatmapFixedPositionMode',
                'setHeatmapColorPalette',
                'setCommonFilters',
            ],
        ],
    })),
    actions(() => ({
        toggleTheme: (theme?: 'light' | 'dark') => ({ theme }),
        toggleMinimized: (minimized?: boolean) => ({ minimized }),
        setHedgehogMode: (hedgehogMode: boolean) => ({ hedgehogMode }),
        setDragPosition: (x: number, y: number) => ({ x, y }),
        setHedgehogActor: (actor: HedgehogActor | null) => ({ actor }),
        syncWithHedgehog: true,
        setVisibleMenu: (visibleMenu: MenuState) => ({
            visibleMenu,
        }),
        onMouseDown: (event: MouseEvent) => ({ event }),
        setDragging: (dragging = true) => ({ dragging }),
        setElement: (element: HTMLElement | null) => ({ element }),
        setMenu: (element: HTMLElement | null) => ({ element }),
        setIsBlurred: (isBlurred: boolean) => ({ isBlurred }),
        setIsEmbeddedInApp: (isEmbedded: boolean) => ({ isEmbedded }),
    })),
    windowValues(() => ({
        windowHeight: (window: Window) => window.innerHeight,
        windowWidth: (window: Window) => Math.min(window.innerWidth, window.document.body.clientWidth),
    })),
    reducers(() => ({
        element: [
            null as HTMLElement | null,
            {
                setElement: (_, { element }) => element,
            },
        ],
        menu: [
            null as HTMLElement | null,
            {
                setMenu: (_, { element }) => element,
            },
        ],

        visibleMenu: [
            'none' as MenuState,
            {
                setVisibleMenu: (_, { visibleMenu }) => visibleMenu,
                setHedgehogMode: (state, { hedgehogMode }) =>
                    hedgehogMode ? 'hedgehog' : state === 'hedgehog' ? 'none' : state,
            },
        ],
        minimized: [
            false,
            { persist: true },
            {
                toggleMinimized: (state, { minimized }) => minimized ?? !state,
            },
        ],
        // Whether the toolbar is not in focus anymore (typically due to clicking elsewhere)
        isBlurred: [
            false,
            {
                setIsBlurred: (_, { isBlurred }) => isBlurred,
                setVisibleMenu: () => false,
            },
        ],
        theme: [
            'dark' as 'light' | 'dark',
            { persist: true },
            {
                toggleTheme: (state, { theme }) => theme ?? (state === 'light' ? 'dark' : 'light'),
            },
        ],
        isDragging: [
            false,
            {
                setDragging: (_, { dragging }) => dragging,
            },
        ],
        lastDragPosition: [
            null as null | {
                x: number
                y: number
            },
            { persist: true },
            {
                setDragPosition: (_, { x, y }) => ({ x, y }),
            },
        ],
        hedgehogMode: [
            false,
            { persist: true },
            {
                setHedgehogMode: (_, { hedgehogMode }) => hedgehogMode,
            },
        ],
        hedgehogActor: [
            null as HedgehogActor | null,
            {
                setHedgehogActor: (_, { actor }) => actor,
            },
        ],
        isEmbeddedInApp: [
            false,
            {
                setIsEmbeddedInApp: (_, { isEmbedded }) => isEmbedded,
            },
        ],
    })),
    selectors({
        dragPosition: [
            (s) => [s.element, s.lastDragPosition, s.windowWidth, s.windowHeight],
            (element, lastDragPosition, windowWidth, windowHeight) => {
                lastDragPosition ??= { x: windowWidth * 0.5, y: windowHeight * 0.5 }

                // If the element isn't set yet we can just guess the size
                const elWidth = (element?.offsetWidth ?? 40) + 2 // account for border
                const elHeight = (element?.offsetHeight ?? 40) + 2 // account for border

                return {
                    x: inBounds(MARGIN, lastDragPosition.x, windowWidth - elWidth - MARGIN),
                    y: inBounds(MARGIN, lastDragPosition.y, windowHeight - elHeight - MARGIN),
                }
            },
        ],

        menuProperties: [
            (s) => [s.element, s.menu, s.dragPosition, s.windowWidth, s.windowHeight, s.isBlurred],
            (element, menu, dragPosition, windowWidth, windowHeight, isBlurred) => {
                if (!element || !menu) {
                    return {}
                }

                const elWidth = element.offsetWidth + 2 // account for border
                const elHeight = element.offsetHeight + 2 // account for border
                const margin = 10

                const isBelow = dragPosition.y + elHeight * 0.5 < windowHeight * 0.5

                let maxHeight = isBelow
                    ? windowHeight - dragPosition.y - elHeight - margin * 2
                    : dragPosition.y - margin * 2

                maxHeight = isBlurred ? 0 : inBounds(0, maxHeight, windowHeight * 0.6)

                const desiredY = isBelow ? dragPosition.y + elHeight + margin : dragPosition.y - margin
                const desiredX = dragPosition.x + elWidth * 0.5

                const top = inBounds(MARGIN, desiredY, windowHeight - elHeight)
                const left = inBounds(
                    MARGIN + menu.clientWidth * 0.5,
                    desiredX,
                    windowWidth - menu.clientWidth * 0.5 - MARGIN
                )

                return {
                    transform: `translate(${left}px, ${top}px)`,
                    maxHeight,
                    isBelow,
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setVisibleMenu: ({ visibleMenu }) => {
            if (visibleMenu === 'heatmap') {
                actions.enableHeatmap()
                values.hedgehogActor?.setAnimation('heatmaps')
            } else if (visibleMenu === 'actions') {
                actions.showButtonActions()
                values.hedgehogActor?.setAnimation('action')
            } else if (visibleMenu === 'flags') {
                values.hedgehogActor?.setAnimation('flag')
            } else if (visibleMenu === 'inspect') {
                actions.enableInspect()
                values.hedgehogActor?.setAnimation('inspect')
            } else {
                actions.disableInspect()
                actions.disableHeatmap()
                actions.hideButtonActions()
                actions.selectAction(null)
            }
        },

        onMouseDown: ({ event }) => {
            if (!values.element || event.button !== 0) {
                return
            }

            const originContainerBounds = values.element.getBoundingClientRect()

            // removeAllListeners(cache)
            const offsetX = event.pageX - originContainerBounds.left
            const offsetY = event.pageY - originContainerBounds.top
            let movedCount = 0
            const moveThreshold = 5

            const onMouseMove = (e: MouseEvent): void => {
                movedCount += 1

                if (movedCount > moveThreshold) {
                    actions.setDragging(true)
                    // Set drag position offset by where we clicked and where the element is
                    actions.setDragPosition(e.pageX - offsetX, e.pageY - offsetY)
                }
            }

            const onMouseUp = (e: MouseEvent): void => {
                if (e.button === 0) {
                    actions.setDragging(false)
                    document.removeEventListener('mousemove', onMouseMove)
                    document.removeEventListener('mouseup', onMouseUp)
                }
            }
            document.addEventListener('mousemove', onMouseMove)
            document.addEventListener('mouseup', onMouseUp)
        },

        setDragging: ({ dragging }) => {
            if (values.hedgehogActor) {
                values.hedgehogActor.isDragging = dragging
                values.hedgehogActor.update()
            }
        },

        syncWithHedgehog: () => {
            const actor = values.hedgehogActor
            if (!values.hedgehogMode || !actor) {
                return
            }
            const pageX = actor.x + SPRITE_SIZE * 0.5 - (values.element?.getBoundingClientRect().width ?? 0) * 0.5
            const pageY =
                values.windowHeight - actor.y - SPRITE_SIZE - (values.element?.getBoundingClientRect().height ?? 0)

            actions.setDragPosition(pageX, pageY)
        },

        toggleMinimized: () => {
            const sync = (): void => {
                // Hack to trigger correct positioning
                actions.syncWithHedgehog()
                if (values.lastDragPosition) {
                    actions.setDragPosition(values.lastDragPosition.x, values.lastDragPosition.y)
                }
            }
            sync()
            // Sync position after the animation completes
            setTimeout(() => sync(), 150)
            setTimeout(() => sync(), 300)
            setTimeout(() => sync(), 550)
        },
        createAction: () => {
            actions.setVisibleMenu('actions')
        },
    })),
    afterMount(({ actions, values, cache }) => {
        cache.clickListener = (e: MouseEvent): void => {
            const shouldBeBlurred = (e.target as HTMLElement)?.id !== TOOLBAR_ID
            if (shouldBeBlurred && !values.isBlurred) {
                actions.setIsBlurred(true)
            }
        }

        // Post message up to parent in case we are embedded in an app
        cache.iframeEventListener = (e: MessageEvent): void => {
            // TODO: Probably need to have strict checks here
            const type: PostHogAppToolbarEvent = e?.data?.type

            if (!type || !type.startsWith('ph-')) {
                return
            }

            switch (type) {
                case PostHogAppToolbarEvent.PH_APP_INIT:
                    actions.setIsEmbeddedInApp(true)
                    actions.patchHeatmapFilters(e.data.payload.filters)
                    actions.setHeatmapColorPalette(e.data.payload.colorPalette)
                    actions.setHeatmapFixedPositionMode(e.data.payload.fixedPositionMode)
                    actions.setCommonFilters(e.data.payload.commonFilters)
                    window.parent.postMessage({ type: PostHogAppToolbarEvent.PH_TOOLBAR_READY }, '*')
                    return
                case PostHogAppToolbarEvent.PH_HEATMAPS_CONFIG:
                    actions.enableHeatmap()
                    return
                case PostHogAppToolbarEvent.PH_PATCH_HEATMAP_FILTERS:
                    actions.patchHeatmapFilters(e.data.payload.filters)
                    return
                case PostHogAppToolbarEvent.PH_HEATMAPS_FIXED_POSITION_MODE:
                    actions.setHeatmapFixedPositionMode(e.data.payload.fixedPositionMode)
                    return
                case PostHogAppToolbarEvent.PH_HEATMAPS_COLOR_PALETTE:
                    actions.setHeatmapColorPalette(e.data.payload.colorPalette)
                    return
                case PostHogAppToolbarEvent.PH_HEATMAPS_COMMON_FILTERS:
                    actions.setCommonFilters(e.data.payload.commonFilters)
                    return
                default:
                    console.warn(`[PostHog Toolbar] Received unknown parent window message: ${type}`)
            }
        }
        window.addEventListener('mousedown', cache.clickListener)
        window.addEventListener('message', cache.iframeEventListener, false)
        // Tell the parent window that we are ready
        window.parent.postMessage({ type: PostHogAppToolbarEvent.PH_TOOLBAR_INIT }, '*')
    }),
    beforeUnmount(({ cache }) => {
        window.removeEventListener('mousedown', cache.clickListener)
        window.removeEventListener('message', cache.iframeEventListener, false)
    }),
])
