import { kea } from 'kea'
import { inBounds } from '~/toolbar/utils'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { toolbarButtonLogicType } from './toolbarButtonLogicType'
import { posthog } from '~/toolbar/posthog'

export const toolbarButtonLogic = kea<toolbarButtonLogicType>({
    actions: () => ({
        showHeatmapInfo: true,
        hideHeatmapInfo: true,
        showActionsInfo: true,
        hideActionsInfo: true,
        showFlags: true,
        hideFlags: true,
        setExtensionPercentage: (percentage: number) => ({ percentage }),
        saveDragPosition: (x: number, y: number) => ({ x, y }),
        setDragPosition: (x: number, y: number) => ({ x, y }),
        saveHeatmapPosition: (x: number, y: number) => ({ x, y }),
        saveActionsPosition: (x: number, y: number) => ({ x, y }),
        saveFlagsPosition: (x: number, y: number) => ({ x, y }),
    }),

    windowValues: () => ({
        windowHeight: (window) => window.innerHeight,
        windowWidth: (window) => Math.min(window.innerWidth, window.document.body.clientWidth),
    }),

    reducers: () => ({
        heatmapInfoVisible: [
            false,
            {
                showHeatmapInfo: () => true,
                hideHeatmapInfo: () => false,
                [heatmapLogic.actionTypes.disableHeatmap]: () => false,
                [heatmapLogic.actionTypes.enableHeatmap]: () => false,
            },
        ],
        actionsInfoVisible: [
            false,
            {
                showActionsInfo: () => true,
                hideActionsInfo: () => false,
                [actionsTabLogic.actionTypes.showButtonActions]: () => false,
                [actionsTabLogic.actionTypes.hideButtonActions]: () => false,
            },
        ],
        flagsVisible: [
            false,
            {
                showFlags: () => true,
                hideFlags: () => false,
            },
        ],
        extensionPercentage: [
            0,
            {
                setExtensionPercentage: (_, { percentage }) => percentage,
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
        heatmapPosition: [
            { x: 100, y: 100 },
            {
                saveHeatmapPosition: (_, { x, y }) => ({ x, y }),
            },
        ],
        actionsPosition: [
            { x: 120, y: 100 } as {
                x: number
                y: number
            },
            {
                saveActionsPosition: (_, { x, y }) => ({ x, y }),
            },
        ],
        flagsPosition: [
            { x: 140, y: 100 } as { x: number; y: number },
            {
                saveFlagsPosition: (_, { x, y }) => ({ x, y }),
            },
        ],
    }),

    selectors: {
        dragPosition: [
            (s) => [s.lastDragPosition, s.windowWidth, s.windowHeight],
            (lastDragPosition, windowWidth, windowHeight) => {
                const widthPadding = 35
                const heightPadding = 30

                const { x, y } = lastDragPosition || {
                    x: -widthPadding,
                    y: 60,
                }
                const dragX = x < 0 ? windowWidth + x : x
                const dragY = y < 0 ? windowHeight + y : y

                return {
                    x: inBounds(widthPadding, dragX, windowWidth - widthPadding),
                    y: inBounds(heightPadding, dragY, windowHeight - heightPadding),
                }
            },
        ],
        toolbarListVerticalPadding: [
            (s) => [s.dragPosition, s.windowHeight],
            ({ y }, windowHeight) => {
                if (y < 90) {
                    return -60 + 90 - y
                } else if (y > windowHeight - 160) {
                    return -60 - (160 - (windowHeight - y))
                }
                return -60
            },
        ],
        helpButtonOnTop: [(s) => [s.dragPosition, s.windowHeight], ({ y }, windowHeight) => y > windowHeight - 100],
        side: [
            (s) => [s.dragPosition, s.windowWidth],
            ({ x }, windowWidth) => (x < windowWidth / 2 ? 'left' : 'right'),
        ],
        closeDistance: [
            (s) => [s.dragPosition, s.windowWidth],
            ({ x, y }, windowWidth) => 58 + (x > windowWidth - 40 || y < 80 ? -28 : 0) + (y < 40 ? -6 : 0),
        ],
        closeRotation: [
            (s) => [s.dragPosition, s.windowWidth],
            ({ x, y }, windowWidth) => -54 + (x > windowWidth - 40 || y < 80 ? 10 : 0) + (y < 40 ? 10 : 0),
        ],
        inspectExtensionPercentage: [
            (s) => [elementsLogic.selectors.inspectEnabled, s.extensionPercentage],
            (inspectEnabled, extensionPercentage) =>
                inspectEnabled ? Math.max(extensionPercentage, 0.53) : extensionPercentage,
        ],
        heatmapExtensionPercentage: [
            (s) => [heatmapLogic.selectors.heatmapEnabled, s.extensionPercentage],
            (heatmapEnabled, extensionPercentage) =>
                heatmapEnabled ? Math.max(extensionPercentage, 0.53) : extensionPercentage,
        ],
        heatmapWindowVisible: [
            (s) => [s.heatmapInfoVisible, heatmapLogic.selectors.heatmapEnabled],
            (heatmapInfoVisible, heatmapEnabled) => heatmapInfoVisible && heatmapEnabled,
        ],
        actionsExtensionPercentage: [
            (s) => [actionsTabLogic.selectors.buttonActionsVisible, s.extensionPercentage],
            (buttonActionsVisible, extensionPercentage) =>
                buttonActionsVisible ? Math.max(extensionPercentage, 0.53) : extensionPercentage,
        ],
        actionsWindowVisible: [
            (s) => [s.actionsInfoVisible, actionsTabLogic.selectors.buttonActionsVisible],
            (actionsInfoVisible, buttonActionsVisible) => actionsInfoVisible && buttonActionsVisible,
        ],
        featureFlagsExtensionPercentage: [
            (s) => [s.flagsVisible, s.extensionPercentage],
            (flagsVisible, extensionPercentage) =>
                flagsVisible ? Math.max(extensionPercentage, 0.53) : extensionPercentage,
        ],
    },

    listeners: ({ actions, values }) => ({
        hideActionsInfo: () => {
            actionsTabLogic.actions.selectAction(null)
        },
        showFlags: () => {
            posthog.capture('toolbar mode triggered', { mode: 'flags', enabled: true })
        },
        hideFlags: () => {
            posthog.capture('toolbar mode triggered', { mode: 'flags', enabled: false })
        },
        saveDragPosition: ({ x, y }) => {
            const { windowWidth, windowHeight } = values
            actions.setDragPosition(
                x > windowWidth / 2 ? -(windowWidth - x) : x,
                y > windowHeight / 2 ? -(windowHeight - y) : y
            )
        },
    }),
})
