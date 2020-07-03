import { kea } from 'kea'
import { inBounds } from '~/toolbar/utils'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'

export const toolbarButtonLogic = kea({
    actions: () => ({
        showHeatmapInfo: true,
        hideHeatmapInfo: true,
        showActionsInfo: true,
        hideActionsInfo: true,
        showStats: true,
        hideStats: true,
        setExtensionPercentage: (percentage) => ({ percentage }),
        saveDragPosition: (x, y) => ({ x, y }),
        saveHeatmapPosition: (x, y) => ({ x, y }),
        saveActionsPosition: (x, y) => ({ x, y }),
        saveStatsPosition: (x, y) => ({ x, y }),
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
                [heatmapLogic.actions.disableHeatmap]: () => false,
                [heatmapLogic.actions.enableHeatmap]: () => false,
            },
        ],
        actionsInfoVisible: [
            false,
            {
                showActionsInfo: () => true,
                hideActionsInfo: () => false,
                [actionsTabLogic.actions.showButtonActions]: () => false,
                [actionsTabLogic.actions.hideButtonActions]: () => false,
            },
        ],
        statsVisible: [
            false,
            {
                showStats: () => true,
                hideStats: () => false,
            },
        ],
        extensionPercentage: [
            0,
            {
                setExtensionPercentage: (_, { percentage }) => percentage,
            },
        ],
        lastDragPosition: [
            null,
            { persist: true },
            {
                saveDragPosition: (state, { x, y }) => ({ x, y }),
            },
        ],
        heatmapPosition: [
            { x: 100, y: 100 },
            {
                saveHeatmapPosition: (state, { x, y }) => ({ x, y }),
            },
        ],
        actionsPosition: [
            { x: 120, y: 100 },
            {
                saveActionsPosition: (state, { x, y }) => ({ x, y }),
            },
        ],
        statsPosition: [
            { x: 140, y: 100 },
            {
                saveStatsPosition: (state, { x, y }) => ({ x, y }),
            },
        ],
    }),

    selectors: {
        dragPosition: [
            (s) => [s.lastDragPosition, s.windowWidth, s.windowHeight],
            (lastDragPosition, windowWidth, windowHeight) => {
                const widthPadding = 35
                const heightPadding = 30
                return {
                    x: inBounds(
                        widthPadding,
                        !lastDragPosition ? windowWidth - widthPadding : lastDragPosition.x,
                        windowWidth - widthPadding
                    ),
                    y: inBounds(
                        heightPadding,
                        !lastDragPosition ? 60 : lastDragPosition.y,
                        windowHeight - heightPadding
                    ),
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
        dockButtonOnTop: [(s) => [s.dragPosition, s.windowHeight], ({ y }, windowHeight) => y > windowHeight - 100],
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
        statsExtensionPercentage: [
            (s) => [s.statsVisible, s.extensionPercentage],
            (statsVisible, extensionPercentage) =>
                statsVisible ? Math.max(extensionPercentage, 0.53) : extensionPercentage,
        ],
    },

    listeners: () => ({
        hideActionsInfo: () => {
            actionsTabLogic.actions.selectAction(null)
        },
    }),
})
