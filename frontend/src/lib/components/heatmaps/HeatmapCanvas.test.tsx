import { fireEvent, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { HeatmapCanvas } from './HeatmapCanvas'

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
