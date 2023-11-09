import { windowValues } from 'kea-window-values'
import { kea, path, connect, actions, reducers, selectors, listeners } from 'kea'
import { getShadowRoot, inBounds } from '~/toolbar/utils'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import type { toolbarButtonLogicType } from './toolbarButtonLogicType'
import { posthog } from '~/toolbar/posthog'
import { HedgehogActor } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { subscriptions } from 'kea-subscriptions'

const DEFAULT_PADDING = { width: 35, height: 30 }
const DEFAULT_PADDING_3000 = { width: 35, height: 3000 }

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
        saveDragPosition: (x: number, y: number) => ({ x, y }),
        setDragPosition: (x: number, y: number) => ({ x, y }),
        setHedgehogActor: (actor: HedgehogActor) => ({ actor }),
        setBoundingRect: (boundingRect: DOMRect) => ({ boundingRect }),
        setVisibleMenu: (visibleMenu: MenuState) => ({
            visibleMenu,
        }),
    })),
    windowValues(() => ({
        windowHeight: (window: Window) => window.innerHeight,
        windowWidth: (window: Window) => Math.min(window.innerWidth, window.document.body.clientWidth),
    })),
    reducers(() => ({
        visibleMenu: [
            'none' as MenuState,
            {
                setVisibleMenu: (_, { visibleMenu }) => visibleMenu,
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
                setBoundingRect: (state, { boundingRect }) => {
                    if (state.height === boundingRect.height && state.width === boundingRect.width) {
                        return state
                    }
                    return { width: boundingRect.width + 5, height: boundingRect.height + 5 }
                },
                setHedgehogMode: (state, { hedgehogMode }) => {
                    if (state === DEFAULT_PADDING && hedgehogMode) {
                        return DEFAULT_PADDING_3000
                    } else {
                        return state
                    }
                },
            },
        ],
    })),
    selectors({
        dragPosition: [
            (s) => [s.padding, s.lastDragPosition, s.windowWidth, s.windowHeight],
            (padding, lastDragPosition, windowWidth, windowHeight) => {
                const widthPadding = padding.width
                const heightPadding = padding.height

                const { x, y } = lastDragPosition || {
                    x: -widthPadding,
                    y: 60,
                }
                const dragX = x < 0 ? windowWidth + x : x
                const dragY = y < 0 ? windowHeight + y : y

                return {
                    x: inBounds(DEFAULT_PADDING.width, dragX, windowWidth - widthPadding),
                    y: inBounds(DEFAULT_PADDING.height, dragY, windowHeight - heightPadding),
                }
            },
        ],
        helpButtonOnTop: [(s) => [s.dragPosition, s.windowHeight], ({ y }, windowHeight) => y > windowHeight - 100],
        side: [
            (s) => [s.dragPosition, s.windowWidth],
            ({ x }, windowWidth) => (x < windowWidth / 2 ? 'left' : 'right'),
        ],
        hedgehogModeDistance: [
            (s) => [s.dragPosition, s.windowWidth],
            ({ x, y }, windowWidth) => 90 + (x > windowWidth - 40 || y < 80 ? -28 : 0) + (y < 40 ? -6 : 0),
        ],
        hedgehogModeRotation: [
            (s) => [s.dragPosition, s.windowWidth],
            ({ x, y }, windowWidth) => -68 + (x > windowWidth - 40 || y < 80 ? 10 : 0) + (y < 40 ? 10 : 0),
        ],
        closeDistance: [
            (s) => [s.dragPosition, s.windowWidth],
            ({ x, y }, windowWidth) => 58 + (x > windowWidth - 40 || y < 80 ? -28 : 0) + (y < 40 ? -6 : 0),
        ],
        closeRotation: [
            (s) => [s.dragPosition, s.windowWidth],
            ({ x, y }, windowWidth) => -54 + (x > windowWidth - 40 || y < 80 ? 10 : 0) + (y < 40 ? 10 : 0),
        ],
    }),
    listeners(({ actions, values }) => ({
        setVisibleMenu: ({ visibleMenu }) => {
            if (visibleMenu === 'heatmap') {
                actions.enableHeatmap()
            } else if (visibleMenu === 'actions') {
                actions.showButtonActions()
            } else if (visibleMenu === 'flags') {
                // purposefully blank
            } else if (visibleMenu === 'inspect') {
                actions.enableInspect()
            } else {
                actions.disableInspect()
                actions.disableHeatmap()
                actions.hideButtonActions()
            }
        },
        showFlags: () => {
            posthog.capture('toolbar mode triggered', { mode: 'flags', enabled: true })
            values.hedgehogActor?.setAnimation('flag')
        },
        hideFlags: () => {
            posthog.capture('toolbar mode triggered', { mode: 'flags', enabled: false })
        },
        showHeatmapInfo: () => {
            values.hedgehogActor?.setAnimation('heatmaps')
        },
        showButtonActions: () => {
            values.hedgehogActor?.setAnimation('action')
        },
        hideActionsInfo: () => {
            actionsTabLogic.actions.selectAction(null)
        },
        enableInspect: () => {
            values.hedgehogActor?.setAnimation('inspect')
        },
        saveDragPosition: ({ x, y }) => {
            const { windowWidth, windowHeight } = values
            actions.setDragPosition(
                x > windowWidth / 2 ? -(windowWidth - x) : x,
                y > windowHeight / 2 ? -(windowHeight - y) : y
            )
        },
    })),
    subscriptions({
        theme: (theme) => {
            const toolbarElement = getShadowRoot()?.getElementById('button-toolbar')
            toolbarElement?.setAttribute('theme', theme)
        },
    }),
])
