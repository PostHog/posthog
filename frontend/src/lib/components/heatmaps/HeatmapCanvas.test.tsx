import { fireEvent, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { HeatmapCanvas } from './HeatmapCanvas'
import { heatmapDataLogic } from './heatmapDataLogic'

const mockSetData = jest.fn()
const mockConfigure = jest.fn()
const mockGetValueAt = jest.fn()

jest.mock('heatmap.js', () => ({
    __esModule: true,
    default: {
        create: () => ({
            setData: (...args: unknown[]) => mockSetData(...args),
            configure: (...args: unknown[]) => mockConfigure(...args),
            getValueAt: (...args: unknown[]) => mockGetValueAt(...args),
        }),
    },
}))

// When the heatmap container has zero height at create time (iframe/data still loading),
// heatmap.js's canvas reads throw: IndexSizeError from getImageData in Chromium, a raw
// NS_ERROR_FAILURE value in Firefox. These must not crash the scene.
describe('HeatmapCanvas', () => {
    beforeEach(() => {
        initKeaTests()
        mockSetData.mockReset()
        mockConfigure.mockReset()
        mockGetValueAt.mockReset()
    })

    it('does not crash when configure throws on a zero-height canvas', () => {
        mockConfigure.mockImplementation(() => {
            throw new DOMException(
                "Failed to execute 'getImageData' on 'CanvasRenderingContext2D': The source height is 0.",
                'IndexSizeError'
            )
        })

        const { container } = render(<HeatmapCanvas context="in-app" />)

        expect(mockConfigure).toHaveBeenCalled()
        expect(container.querySelector('[data-attr="heatmap-canvas"]')).toBeTruthy()
    })

    it('places and hit-tests points at the rendered width when the preview is narrower than the analysis width', () => {
        const logic = heatmapDataLogic({ context: 'in-app' })
        logic.mount()
        logic.actions.setWindowWidthOverride(1024)
        logic.actions.loadHeatmapSuccess({
            results: [{ pointer_relative_x: 0.5, pointer_target_fixed: false, pointer_y: 100, count: 3 }],
        })

        const { container } = render(<HeatmapCanvas context="in-app" widthOverride={512} />)

        expect(mockSetData).toHaveBeenLastCalledWith(expect.objectContaining({ data: [{ x: 256, y: 50, value: 3 }] }))

        fireEvent.click(container.querySelector('[data-attr="heatmap-canvas"]')!, { clientX: 256, clientY: 50 })
        expect(logic.values.selectedArea?.points).toEqual([{ x: 0.5, y: 100, target_fixed: false }])

        logic.actions.clearSelectedArea()
        fireEvent.click(container.querySelector('[data-attr="heatmap-canvas"]')!, { clientX: 512, clientY: 100 })
        expect(logic.values.selectedArea).toBeNull()
    })

    it('does not crash when getValueAt throws during mouse tracking', () => {
        mockGetValueAt.mockImplementation(() => {
            // Firefox throws a raw non-Error value from a broken canvas
            throw 'NS_ERROR_FAILURE'
        })

        const { container } = render(<HeatmapCanvas context="in-app" />)
        fireEvent.mouseMove(window, { clientX: 10, clientY: 10 })

        expect(mockGetValueAt).toHaveBeenCalled()
        expect(container.querySelector('[data-attr="heatmap-canvas"]')).toBeTruthy()
    })
})
