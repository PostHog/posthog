import { windowValues } from 'kea-window-values'
import { kea, path, connect, actions, reducers, selectors, listeners } from 'kea'
import { getShadowRoot, inBounds } from '~/toolbar/utils'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import type { toolbarButtonLogicType } from './toolbarButtonLogicType'
import { HedgehogActor } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { subscriptions } from 'kea-subscriptions'

const DEFAULT_PADDING = { width: 16, height: 16 }

export type MenuState = 'none' | 'more' | 'heatmap' | 'actions' | 'flags' | 'inspect'

export const toolbarButtonLogic = kea<toolbarButtonLogicType>([
    path(['toolbar', 'button', 'toolbarButtonLogic']),
    connect(() => ({
        actions: [
            actionsTabLogic,
            ['showButtonActions', 'hideButtonActions'],
            elementsLogic,
            ['enableInspect', 'disableInspect'],
            heatmapLogic,
            ['enableHeatmap', 'disableHeatmap'],
        ],
    })),
    actions(() => ({
        toggleTheme: true,
        toggleWidth: true,
        setMenuPlacement: (placement: 'top' | 'bottom') => ({ placement }),
        setHedgehogMode: (hedgehogMode: boolean) => ({ hedgehogMode }),
        setDragPosition: (x: number, y: number) => ({ x, y }),
        setHedgehogActor: (actor: HedgehogActor) => ({ actor }),
        setHedgehogPosition: (actor: HedgehogActor) => ({ actor }),
        setVisibleMenu: (visibleMenu: MenuState) => ({
            visibleMenu,
        }),
        onMouseDown: (event: React.MouseEvent<HTMLDivElement, MouseEvent>) => ({ event }),
        setDragging: (dragging = true) => ({ dragging }),
        setElement: (element: HTMLElement | null) => ({ element }),
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

        visibleMenu: [
            'none' as MenuState,
            {
                setVisibleMenu: (_, { visibleMenu }) => visibleMenu,
                toggleWidth: () => 'none',
            },
        ],
        menuPlacement: [
            'top' as 'top' | 'bottom',
            {
                setMenuPlacement: (_, { placement }) => placement,
            },
        ],
        minimizedWidth: [
            false,
            { persist: true },
            {
                toggleWidth: (state) => !state,
            },
        ],
        theme: [
            'dark' as 'light' | 'dark',
            { persist: true },
            {
                toggleTheme: (state) => (state === 'light' ? 'dark' : 'light'),
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
        padding: [
            DEFAULT_PADDING,
            {
                setHedgehogMode: (_, { hedgehogMode }) => {
                    if (DEFAULT_PADDING && hedgehogMode) {
                        return DEFAULT_PADDING
                    } else {
                        return DEFAULT_PADDING
                    }
                },
            },
        ],
    })),
    selectors({
        dragPosition: [
            (s) => [s.element, s.padding, s.lastDragPosition, s.windowWidth, s.windowHeight],
            (element, padding, lastDragPosition, windowWidth, windowHeight) => {
                if (!element || !lastDragPosition) {
                    return { x: 0, y: 0 }
                }
                const widthPadding = padding.width
                const heightPadding = padding.height
                const elWidth = element.offsetWidth + 2 // account for border
                const elHeight = element.offsetHeight + 2 // account for border

                return {
                    x: inBounds(DEFAULT_PADDING.width, lastDragPosition.x, windowWidth - elWidth - widthPadding),
                    y: inBounds(DEFAULT_PADDING.height, lastDragPosition.y, windowHeight - elHeight - heightPadding),
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
                actionsTabLogic.actions.selectAction(null)
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

        setHedgehogPosition: ({ actor }) => {
            const pageX = actor.x
            const pageY = values.windowHeight - actor.y
            actions.setDragPosition(pageX, pageY)
        },
    })),
    subscriptions({
        theme: (theme) => {
            const toolbarElement = getShadowRoot()?.getElementById('button-toolbar')
            toolbarElement?.setAttribute('theme', theme)
        },
    }),
])
