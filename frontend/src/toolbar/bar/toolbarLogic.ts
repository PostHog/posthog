import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { windowValues } from 'kea-window-values'
import { HedgehogActor } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { SPRITE_SIZE } from 'lib/components/HedgehogBuddy/sprites/sprites'
import { PostHogAppToolbarEvent } from 'lib/components/IframedToolbarBrowser/utils'

import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { inBounds, TOOLBAR_CONTAINER_CLASS, TOOLBAR_ID } from '~/toolbar/utils'

import type { toolbarLogicType } from './toolbarLogicType'

const MARGIN = 2

export type MenuState = 'none' | 'heatmap' | 'actions' | 'flags' | 'inspect' | 'hedgehog' | 'debugger' | 'experiments'
export type ToolbarPositionType =
    | 'top-left'
    | 'top-center'
    | 'top-right'
    | 'bottom-left'
    | 'bottom-center'
    | 'bottom-right'
    | 'left-center'
    | 'right-center'

export const TOOLBAR_FIXED_POSITION_HITBOX = 100

export const toolbarLogic = kea<toolbarLogicType>([
    path(['toolbar', 'bar', 'toolbarLogic']),
    connect(() => ({
        values: [toolbarConfigLogic, ['posthog']],
        actions: [
            actionsTabLogic,
            [
                'showButtonActions',
                'hideButtonActions',
                'selectAction',
                'setAutomaticActionCreationEnabled',
                'actionCreatedSuccess',
            ],
            experimentsTabLogic,
            ['showButtonExperiments'],
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
                'toggleClickmapsEnabled',
                'loadHeatmap',
                'loadHeatmapSuccess',
                'loadHeatmapFailure',
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
        onMouseOrTouchDown: (event: MouseEvent | TouchEvent) => ({ event }),
        setDragging: (dragging = true) => ({ dragging }),
        setElement: (element: HTMLElement | null) => ({ element }),
        setMenu: (element: HTMLElement | null) => ({ element }),
        setIsBlurred: (isBlurred: boolean) => ({ isBlurred }),
        setIsEmbeddedInApp: (isEmbedded: boolean) => ({ isEmbedded }),
        setFixedPosition: (position: ToolbarPositionType) => ({ position }),
        setCurrentPathname: (pathname: string) => ({ pathname }),
        maybeSendNavigationMessage: true,
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
                setFixedPosition: () => null,
            },
        ],
        fixedPosition: [
            'bottom-center' as ToolbarPositionType,
            { persist: true },
            {
                setFixedPosition: (_, { position }) => position,
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
        currentPathname: [
            '',
            {
                setCurrentPathname: (_, { pathname }) => pathname,
            },
        ],
    })),
    selectors({
        position: [
            (s) => [
                s.element,
                s.lastDragPosition,
                s.windowWidth,
                s.windowHeight,
                s.fixedPosition,
                s.fixedPositions,
                s.minimized,
            ],
            (element, lastDragPosition, windowWidth, windowHeight, fixedPosition, fixedPositions, minimized) => {
                const position = lastDragPosition ?? fixedPositions[fixedPosition]

                const width = element
                    ? parseInt(
                          getComputedStyle(element)
                              .getPropertyValue(minimized ? '--toolbar-width-minimized' : '--toolbar-width-expanded')
                              .replace('px', '')
                      )
                    : 40

                const height = element?.offsetHeight ?? 40

                const xPadding = width * 0.5 + 10
                const yPadding = height * 0.5 + 10

                return {
                    x: inBounds(xPadding, position.x, windowWidth - xPadding),
                    y: inBounds(yPadding, position.y, windowHeight - yPadding),
                }
            },
        ],

        fixedPositions: [
            (s) => [s.windowWidth, s.windowHeight],
            (windowWidth, windowHeight): Record<ToolbarPositionType, { x: number; y: number }> => {
                return {
                    'top-left': {
                        x: 0,
                        y: 0,
                    },
                    'top-center': {
                        x: windowWidth / 2,
                        y: 0,
                    },
                    'top-right': {
                        x: windowWidth,
                        y: 0,
                    },
                    'bottom-left': {
                        x: 0,
                        y: windowHeight,
                    },
                    'bottom-center': {
                        x: windowWidth / 2,
                        y: windowHeight,
                    },
                    'bottom-right': {
                        x: windowWidth,
                        y: windowHeight,
                    },
                    'left-center': {
                        x: 0,
                        y: windowHeight / 2,
                    },
                    'right-center': {
                        x: windowWidth,
                        y: windowHeight / 2,
                    },
                }
            },
        ],
        menuProperties: [
            (s) => [s.element, s.menu, s.position, s.windowWidth, s.windowHeight, s.isBlurred],
            (element, menu, position, windowWidth, windowHeight, isBlurred) => {
                if (!element || !menu) {
                    return {}
                }

                const margin = 10
                const marginFromPosition = element.offsetHeight * 0.5 + margin

                const isBelow = position.y < windowHeight * 0.5

                // Max space we could fill
                const spaceAboveOrBelow = isBelow ? windowHeight - position.y : position.y
                // Then we remove some margins and half the height of the element
                const maxDesiredHeight = spaceAboveOrBelow - margin - marginFromPosition
                // Finally we don't want it to end up too big
                const finalHeight = isBlurred ? 0 : inBounds(0, maxDesiredHeight, windowHeight * 0.6)

                const desiredY = isBelow ? position.y + marginFromPosition : position.y - marginFromPosition
                const desiredX = position.x

                const top = inBounds(MARGIN, desiredY, windowHeight)
                const left = inBounds(
                    MARGIN + menu.clientWidth * 0.5,
                    desiredX,
                    windowWidth - menu.clientWidth * 0.5 - MARGIN
                )

                return {
                    transform: `translate(${left}px, ${top}px)`,
                    maxHeight: finalHeight,
                    isBelow,
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setVisibleMenu: ({ visibleMenu }) => {
            if (visibleMenu === 'heatmap') {
                actions.enableHeatmap()
                values.hedgehogActor?.setOnFire(1)
            } else if (visibleMenu === 'actions') {
                actions.showButtonActions()
                values.hedgehogActor?.setAnimation('action')
            } else if (visibleMenu === 'experiments') {
                actions.showButtonExperiments()
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

        onMouseOrTouchDown: ({ event }) => {
            const isTouchEvent = 'touches' in event

            if (!values.element || (!isTouchEvent && event.button !== 0)) {
                return
            }

            const touchX = isTouchEvent ? event.touches[0].pageX : event.pageX
            const touchY = isTouchEvent ? event.touches[0].pageY : event.pageY

            const offsetX = touchX - values.position.x
            const offsetY = touchY - values.position.y
            let movedCount = 0
            const moveThreshold = 5

            const onMove = (moveEvent: MouseEvent | TouchEvent): void => {
                movedCount += 1
                const isMoveTouchEvent = 'touches' in moveEvent

                const moveTouchX = isMoveTouchEvent ? moveEvent.touches[0].pageX : moveEvent.pageX
                const moveTouchY = isMoveTouchEvent ? moveEvent.touches[0].pageY : moveEvent.pageY

                if (movedCount > moveThreshold) {
                    actions.setDragging(true)
                    // Set drag position offset by where we clicked and where the element is

                    // Check if near any of the fixed positions and set to them if so, otherwise set to mouse position

                    const fixedPositions = values.fixedPositions

                    let closestPosition: ToolbarPositionType | null = null

                    for (const [position, { x, y }] of Object.entries(fixedPositions)) {
                        const distance = Math.sqrt((moveTouchX - x) ** 2 + (moveTouchY - y) ** 2)

                        if (distance < TOOLBAR_FIXED_POSITION_HITBOX) {
                            closestPosition = position as ToolbarPositionType
                            break
                        }
                    }

                    if (closestPosition) {
                        actions.setFixedPosition(closestPosition)
                    } else {
                        actions.setDragPosition(moveTouchX - offsetX, moveTouchY - offsetY)
                    }
                }
            }

            if (isTouchEvent) {
                const onTouchEnd = (): void => {
                    actions.setDragging(false)
                    values.element?.removeEventListener('touchmove', onMove)
                    values.element?.removeEventListener('touchend', onTouchEnd)
                }
                values.element.addEventListener('touchmove', onMove)
                values.element.addEventListener('touchend', onTouchEnd)
            } else {
                const onMouseUp = (e: MouseEvent): void => {
                    if (e.button === 0) {
                        actions.setDragging(false)
                        document.removeEventListener('mousemove', onMove)
                        document.removeEventListener('mouseup', onMouseUp)
                    }
                }
                document.addEventListener('mousemove', onMove)
                document.addEventListener('mouseup', onMouseUp)
            }
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

            const newX = actor.x + SPRITE_SIZE * 0.5
            const newY = values.windowHeight - actor.y - SPRITE_SIZE - 20
            actions.setDragPosition(newX, newY)
        },

        createAction: () => {
            actions.setVisibleMenu('actions')
        },
        loadHeatmap: () => {
            window.parent.postMessage({ type: PostHogAppToolbarEvent.PH_TOOLBAR_HEATMAP_LOADING }, '*')
        },
        loadHeatmapSuccess: () => {
            // if embedded we need to signal start and finish of heatmap loading to the parent
            window.parent.postMessage({ type: PostHogAppToolbarEvent.PH_TOOLBAR_HEATMAP_LOADED }, '*')
        },
        loadHeatmapFailure: () => {
            // if embedded we need to signal start and finish of heatmap loading to the parent
            window.parent.postMessage({ type: PostHogAppToolbarEvent.PH_TOOLBAR_HEATMAP_FAILED }, '*')
        },
        actionCreatedSuccess: (action) => {
            // if embedded, we need to tell the parent window that a new action was created
            window.parent.postMessage({ type: PostHogAppToolbarEvent.PH_NEW_ACTION_CREATED, payload: action }, '*')
        },
        maybeSendNavigationMessage: () => {
            const currentPath = window.location.pathname
            if (currentPath !== values.currentPathname) {
                actions.setCurrentPathname(currentPath)
                window.parent.postMessage(
                    { type: PostHogAppToolbarEvent.PH_TOOLBAR_NAVIGATED, payload: { path: currentPath } },
                    '*'
                )
            }
        },
    })),
    afterMount(({ actions, values, cache }) => {
        cache.clickListener = (e: MouseEvent): void => {
            const target = e.target as HTMLElement
            const clickIsInToolbar = target?.id === TOOLBAR_ID || !!target.closest?.('.' + TOOLBAR_CONTAINER_CLASS)
            if (!clickIsInToolbar && !values.isBlurred) {
                actions.setIsBlurred(true)
            }
        }
        window.addEventListener('mousedown', cache.clickListener)
        window.addEventListener('popstate', () => {
            actions.maybeSendNavigationMessage()
        })

        // Use a setInterval to periodically check for URL changes
        // We do this because we don't want to write over the history.pushState function in case other scripts rely on it
        // And mutation observers don't seem to work :shrug:
        setInterval(() => {
            actions.maybeSendNavigationMessage()
        }, 500)

        // the toolbar can be run within the posthog parent app
        // if it is then it listens to parent messages
        const isInIframe = window !== window.parent

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
                    actions.toggleClickmapsEnabled(false)
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
                case PostHogAppToolbarEvent.PH_ELEMENT_SELECTOR:
                    if (e.data.payload.enabled) {
                        actions.enableInspect()
                    } else {
                        actions.disableInspect()
                        actions.hideButtonActions()
                    }
                    return
                case PostHogAppToolbarEvent.PH_NEW_ACTION_NAME:
                    actions.setAutomaticActionCreationEnabled(true, e.data.payload.name)
                    return
                default:
                    console.warn(`[PostHog Toolbar] Received unknown parent window message: ${type}`)
            }
        }

        if (isInIframe) {
            window.addEventListener('message', cache.iframeEventListener, false)
            // Post message up to parent in case we are embedded in an app
            // Tell the parent window that we are ready
            // we check if we're in an iframe before this setup to avoid logging warnings to the console
            window.parent.postMessage({ type: PostHogAppToolbarEvent.PH_TOOLBAR_INIT }, '*')
        }
    }),
    beforeUnmount(({ cache }) => {
        window.removeEventListener('mousedown', cache.clickListener)
        window.removeEventListener('message', cache.iframeEventListener, false)
    }),
])
