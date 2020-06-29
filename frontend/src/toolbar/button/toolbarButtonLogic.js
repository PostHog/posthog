import { kea } from 'kea'
import { inBounds } from '~/toolbar/utils'

export const toolbarButtonLogic = kea({
    actions: () => ({
        showHeatmapInfo: true,
        hideHeatmapInfo: true,
        setExtensionPercentage: percentage => ({ percentage }),
        saveDragPosition: (x, y) => ({ x, y }),
    }),

    windowValues: () => ({
        windowHeight: window => window.innerHeight,
        windowWidth: window => Math.min(window.innerWidth, window.document.body.clientWidth),
    }),

    reducers: {
        heatmapInfoVisible: [
            false,
            {
                showHeatmapInfo: () => true,
                hideHeatmapInfo: () => false,
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
    },

    selectors: {
        dragPosition: [
            s => [s.lastDragPosition, s.windowWidth, s.windowHeight],
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
            s => [s.dragPosition, s.windowHeight],
            ({ y }, windowHeight) => {
                if (y < 120) {
                    return 120 - y
                } else if (y > windowHeight - 130) {
                    return -(130 - (windowHeight - y))
                }
                return 0
            },
        ],
        dockButtonOnTop: [s => [s.dragPosition, s.windowHeight], ({ y }, windowHeight) => y > windowHeight - 100],
        side: [s => [s.dragPosition, s.windowWidth], ({ x }, windowWidth) => (x < windowWidth / 2 ? 'left' : 'right')],
    },
})
