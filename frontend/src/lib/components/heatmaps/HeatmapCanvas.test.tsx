import { fireEvent, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { HeatmapCanvas } from './HeatmapCanvas'

const mockCreate = jest.fn()
const mockSetData = jest.fn()
const mockConfigure = jest.fn()
const mockGetValueAt = jest.fn()

jest.mock('heatmap.js', () => ({
    __esModule: true,
    default: {
        create: (...args: unknown[]) => {
            mockCreate(...args)
            return {
                setData: (...a: unknown[]) => mockSetData(...a),
                configure: (...a: unknown[]) => mockConfigure(...a),
                getValueAt: (...a: unknown[]) => mockGetValueAt(...a),
            }
        },
    },
}))

let triggerResize: (() => void) | undefined

class ResizeObserverMock {
    constructor(callback: () => void) {
        triggerResize = callback
    }
    observe(): void {}
    disconnect(): void {}
}

// heatmap.js sizes its canvas from the container's height at create time. On a scene where the
// container's height depends on async content (e.g. a screenshot still loading), the old
// create-once behavior left the canvas permanently dead. These tests lock in that create is
// deferred until the container reports a real height, and that resize-driven canvas reads still
// don't crash the scene: IndexSizeError from getImageData in Chromium, a raw NS_ERROR_FAILURE
// value in Firefox.
describe('HeatmapCanvas', () => {
    const originalResizeObserver = global.ResizeObserver

    beforeEach(() => {
        initKeaTests()
        mockCreate.mockReset()
        mockSetData.mockReset()
        mockConfigure.mockReset()
        mockGetValueAt.mockReset()
        triggerResize = undefined
        global.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver
    })

    afterEach(() => {
        global.ResizeObserver = originalResizeObserver
    })

    const renderWithRealHeight = (): HTMLElement => {
        const { container } = render(<HeatmapCanvas context="in-app" />)
        const canvasContainer = container.querySelector('[data-attr="heatmap-canvas"]')?.firstElementChild
        Object.defineProperty(canvasContainer, 'offsetHeight', { value: 200, configurable: true })
        triggerResize?.()
        return container
    }

    it('does not create the heatmap while the container has zero height', () => {
        const { container } = render(<HeatmapCanvas context="in-app" />)

        expect(mockCreate).not.toHaveBeenCalled()
        expect(container.querySelector('[data-attr="heatmap-canvas"]')).toBeTruthy()
    })

    it('does not crash when configure throws once the container gets a real height', () => {
        mockConfigure.mockImplementation(() => {
            throw new DOMException(
                "Failed to execute 'getImageData' on 'CanvasRenderingContext2D': The source height is 0.",
                'IndexSizeError'
            )
        })

        const container = renderWithRealHeight()

        expect(mockCreate).toHaveBeenCalledTimes(1)
        expect(container.querySelector('[data-attr="heatmap-canvas"]')).toBeTruthy()
    })

    it('does not crash when getValueAt throws during mouse tracking', () => {
        mockGetValueAt.mockImplementation(() => {
            // Firefox throws a raw non-Error value from a broken canvas
            throw 'NS_ERROR_FAILURE'
        })

        const container = renderWithRealHeight()
        fireEvent.mouseMove(window, { clientX: 10, clientY: 10 })

        expect(mockGetValueAt).toHaveBeenCalled()
        expect(container.querySelector('[data-attr="heatmap-canvas"]')).toBeTruthy()
    })
})
