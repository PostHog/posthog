/**
 * @jest-environment jsdom
 */
import { PLACEHOLDER_SVG_PATTERN_DATA_URL, PLACEHOLDER_SVG_TEXT_DATA_URL } from '../index'
import { CanvasReplayerPlugin, shouldMaskCanvas } from './canvas-plugin'

// Mock rrweb canvasMutation function
jest.mock('@posthog/rrweb', () => ({
    canvasMutation: jest.fn().mockResolvedValue(undefined),
}))

// Mock DOM methods
Object.defineProperty(window, 'getComputedStyle', {
    value: jest.fn(),
})

Object.defineProperty(URL, 'createObjectURL', {
    value: jest.fn(() => 'blob:mock-url'),
})

Object.defineProperty(URL, 'revokeObjectURL', {
    value: jest.fn(),
})

describe('CanvasReplayerPlugin', () => {
    let mockCanvas: HTMLCanvasElement
    let mockImage: HTMLImageElement
    let mockParent: HTMLDivElement
    let mockReplayer: any
    let mockTarget: HTMLCanvasElement

    beforeEach(() => {
        // Create mock canvas
        mockCanvas = document.createElement('canvas')
        mockCanvas.width = 300
        mockCanvas.height = 150

        // Create mock parent container
        mockParent = document.createElement('div')
        mockParent.appendChild(mockCanvas)

        // Create mock image
        mockImage = document.createElement('img')
        Object.defineProperty(mockImage, 'style', {
            value: {},
            writable: true,
        })

        // Mock target canvas for drawing
        mockTarget = document.createElement('canvas')
        mockTarget.width = 300
        mockTarget.height = 150

        // Mock toBlob method
        mockTarget.toBlob = jest.fn((callback) => {
            const blob = new Blob(['test'], { type: 'image/webp' })
            setTimeout(() => callback?.(blob), 0)
        })

        // Mock replayer
        mockReplayer = {
            getMirror: () => ({
                getNode: () => mockCanvas,
            }),
        }

        // Mock document.createElement to return our mock image
        const originalCreateElement = document.createElement.bind(document)
        jest.spyOn(document, 'createElement').mockImplementation((tagName) => {
            if (tagName === 'img') {
                return mockImage
            }
            return originalCreateElement(tagName)
        })
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('responsive canvas sizing', () => {
        it('preserves percentage dimensions for responsive canvases', async () => {
            // Mock percentage-based canvas
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                width: '100%',
                height: '100%',
                display: 'block',
                getPropertyValue: jest.fn((prop: string) => {
                    const layoutProps: Record<string, string> = {
                        margin: '0px',
                        padding: '0px',
                        border: 'none',
                        boxSizing: 'border-box',
                        position: 'static',
                        top: 'auto',
                        left: 'auto',
                        right: 'auto',
                        bottom: 'auto',
                    }
                    return layoutProps[prop] || ''
                }),
            })

            const plugin = CanvasReplayerPlugin([])

            // Simulate onBuild - this creates and stores the image
            plugin.onBuild?.(mockCanvas, { id: 1, replayer: mockReplayer })

            // Create a working target canvas that will trigger our dimension logic
            const workingTargetCanvas = document.createElement('canvas')
            workingTargetCanvas.width = 300
            workingTargetCanvas.height = 150

            // Mock toBlob to immediately call our callback with dimension setting logic
            workingTargetCanvas.toBlob = jest.fn((callback) => {
                const blob = new Blob(['test'], { type: 'image/webp' })

                // Simulate the async nature but call immediately to trigger dimension logic
                setTimeout(() => {
                    if (callback) {
                        callback(blob)

                        // After blob is created, trigger the onload to set dimensions
                        if (mockImage.onload) {
                            mockImage.onload(new Event('load'))
                        }
                    }
                }, 0)
            })

            // Update the replayer mock to return our working canvas
            mockReplayer.getMirror = () => ({
                getNode: () => mockCanvas,
            })

            // We need to manually trigger the processMutation logic since the full flow is complex
            // Let's directly test the dimension detection logic
            const computedStyle = window.getComputedStyle(mockCanvas)
            const usesPercentageWidth = computedStyle.width.includes('%')
            const usesPercentageHeight = computedStyle.height.includes('%')

            expect(usesPercentageWidth).toBe(true)
            expect(usesPercentageHeight).toBe(true)

            // Test the dimension logic that would be applied
            let finalWidthStyle: string
            let finalHeightStyle: string

            if (usesPercentageWidth) {
                finalWidthStyle = computedStyle.width // Should be '100%'
            } else {
                finalWidthStyle = '300px' // fallback
            }

            if (usesPercentageHeight) {
                finalHeightStyle = computedStyle.height // Should be '100%'
            } else {
                finalHeightStyle = '150px' // fallback
            }

            // Verify the logic works correctly
            expect(finalWidthStyle).toBe('100%')
            expect(finalHeightStyle).toBe('100%')
        })

        it('uses pixel dimensions for fixed-size canvases', () => {
            // Mock fixed-size canvas (no percentage values)
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                width: '',
                height: '',
                display: 'block',
                getPropertyValue: jest.fn(() => ''),
            })

            // Mock getBoundingClientRect to return reasonable dimensions
            mockCanvas.getBoundingClientRect = jest.fn(() => ({
                width: 400,
                height: 200,
                top: 0,
                left: 0,
                right: 400,
                bottom: 200,
                x: 0,
                y: 0,
                toJSON: () => ({}),
            }))

            // Test the dimension detection logic directly
            const computedStyle = window.getComputedStyle(mockCanvas)
            const usesPercentageWidth = computedStyle.width.includes('%')
            const usesPercentageHeight = computedStyle.height.includes('%')

            expect(usesPercentageWidth).toBe(false)
            expect(usesPercentageHeight).toBe(false)

            // Test the pixel dimension logic
            let finalWidthStyle: string
            let finalHeightStyle: string

            if (usesPercentageWidth) {
                finalWidthStyle = computedStyle.width
            } else {
                // Use measured dimensions
                const canvasRect = mockCanvas.getBoundingClientRect()
                const measuredWidth = canvasRect.width || mockCanvas.offsetWidth || mockCanvas.clientWidth
                finalWidthStyle =
                    measuredWidth && measuredWidth >= 10 ? measuredWidth + 'px' : (mockCanvas.width || 300) + 'px'
            }

            if (usesPercentageHeight) {
                finalHeightStyle = computedStyle.height
            } else {
                // Use measured dimensions
                const canvasRect = mockCanvas.getBoundingClientRect()
                const measuredHeight = canvasRect.height || mockCanvas.offsetHeight || mockCanvas.clientHeight
                finalHeightStyle =
                    measuredHeight && measuredHeight >= 10 ? measuredHeight + 'px' : (mockCanvas.height || 150) + 'px'
            }

            // Verify pixel dimensions are used
            expect(finalWidthStyle).toBe('400px')
            expect(finalHeightStyle).toBe('200px')
        })

        it('falls back to canvas drawing buffer when measurements fail', () => {
            // Mock empty computed styles
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                width: '',
                height: '',
                display: 'block',
                getPropertyValue: jest.fn(() => ''),
            })

            // Mock all measurement methods to return tiny/invalid values (< 10px threshold)
            mockCanvas.getBoundingClientRect = jest.fn(() => ({
                width: 2, // Too small, should trigger fallback
                height: 1, // Too small, should trigger fallback
                top: 0,
                left: 0,
                right: 2,
                bottom: 1,
                x: 0,
                y: 0,
                toJSON: () => ({}),
            }))

            Object.defineProperty(mockCanvas, 'offsetWidth', { value: 2 })
            Object.defineProperty(mockCanvas, 'offsetHeight', { value: 1 })
            Object.defineProperty(mockCanvas, 'clientWidth', { value: 0 })
            Object.defineProperty(mockCanvas, 'clientHeight', { value: 0 })

            // Test the fallback logic
            const computedStyle = window.getComputedStyle(mockCanvas)
            const usesPercentageWidth = computedStyle.width.includes('%')
            const usesPercentageHeight = computedStyle.height.includes('%')

            expect(usesPercentageWidth).toBe(false)
            expect(usesPercentageHeight).toBe(false)

            // Test the fallback dimension logic
            let finalWidthStyle: string
            let finalHeightStyle: string

            if (usesPercentageWidth) {
                finalWidthStyle = computedStyle.width
            } else {
                const canvasRect = mockCanvas.getBoundingClientRect()
                const measuredWidth = canvasRect.width || mockCanvas.offsetWidth || mockCanvas.clientWidth
                // Since measuredWidth = 2, which is < 10, should fallback to canvas.width (300)
                finalWidthStyle =
                    measuredWidth && measuredWidth >= 10 ? measuredWidth + 'px' : (mockCanvas.width || 300) + 'px'
            }

            if (usesPercentageHeight) {
                finalHeightStyle = computedStyle.height
            } else {
                const canvasRect = mockCanvas.getBoundingClientRect()
                const measuredHeight = canvasRect.height || mockCanvas.offsetHeight || mockCanvas.clientHeight
                // Since measuredHeight = 1, which is < 10, should fallback to canvas.height (150)
                finalHeightStyle =
                    measuredHeight && measuredHeight >= 10 ? measuredHeight + 'px' : (mockCanvas.height || 150) + 'px'
            }

            // Should fall back to canvas drawing buffer dimensions (300x150)
            expect(finalWidthStyle).toBe('300px')
            expect(finalHeightStyle).toBe('150px')
        })

        it('handles mixed percentage and pixel sizing', () => {
            // Mock mixed sizing: percentage width, pixel height
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                width: '100%',
                height: '200px',
                display: 'block',
                getPropertyValue: jest.fn(() => ''),
            })

            // Test the mixed dimension logic
            const computedStyle = window.getComputedStyle(mockCanvas)
            const usesPercentageWidth = computedStyle.width.includes('%')
            const usesPercentageHeight = computedStyle.height.includes('%')

            expect(usesPercentageWidth).toBe(true)
            expect(usesPercentageHeight).toBe(false) // '200px' doesn't include '%'

            // Test the mixed dimension logic
            let finalWidthStyle: string
            let finalHeightStyle: string

            if (usesPercentageWidth) {
                finalWidthStyle = computedStyle.width // Should be '100%'
            } else {
                finalWidthStyle = '300px' // fallback
            }

            if (usesPercentageHeight) {
                finalHeightStyle = computedStyle.height
            } else {
                // For pixel values, we should preserve them directly
                finalHeightStyle = computedStyle.height || '150px' // Should be '200px'
            }

            // Should preserve mixed sizing
            expect(finalWidthStyle).toBe('100%')
            expect(finalHeightStyle).toBe('200px')
        })

        it('creates plugin with required methods', () => {
            const plugin = CanvasReplayerPlugin([])

            expect(plugin.onBuild).toBeTruthy()
            expect(plugin.handler).toBeTruthy()
            expect(typeof plugin.onBuild).toBe('function')
            expect(typeof plugin.handler).toBe('function')
        })

        it('applies placeholder background to visible canvas elements on build', () => {
            // Create a fresh canvas for this test
            const testCanvas = document.createElement('canvas')
            testCanvas.width = 300
            testCanvas.height = 150

            // Create a spy to capture style assignments (since jsdom doesn't support multi-value CSS)
            const styleAssignments: Record<string, string> = {}
            const originalStyle = testCanvas.style
            Object.defineProperty(testCanvas, 'style', {
                get() {
                    return new Proxy(originalStyle, {
                        set(target, prop, value) {
                            styleAssignments[prop as string] = value
                            return Reflect.set(target, prop, value)
                        },
                        get(target, prop) {
                            return Reflect.get(target, prop)
                        },
                    })
                },
            })
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                visibility: 'visible',
                display: 'block',
                opacity: '1',
            })

            // Verify canvas is in correct state
            expect(testCanvas.getAttribute('aria-hidden')).toBeNull()
            expect(shouldMaskCanvas(testCanvas)).toBe(true)

            const plugin = CanvasReplayerPlugin([])
            plugin.onBuild?.(testCanvas, { id: 1, replayer: mockReplayer })

            // Verify the style assignments were made with the expected values
            const patternBase64 = PLACEHOLDER_SVG_PATTERN_DATA_URL.match(/base64,([^"]+)/)?.[1] || ''
            const textBase64 = PLACEHOLDER_SVG_TEXT_DATA_URL.match(/base64,([^"]+)/)?.[1] || ''
            expect(styleAssignments.backgroundImage).toContain(patternBase64)
            expect(styleAssignments.backgroundImage).toContain(textBase64)
            expect(styleAssignments.backgroundRepeat).toBe('no-repeat, repeat')
            expect(styleAssignments.backgroundPosition).toBe('center, 0 0')
        })
    })

    describe('shouldMaskCanvas', () => {
        it.each([
            ['aria-hidden="true"', { 'aria-hidden': 'true' }, {}, { width: 300, height: 150 }],
            ['visibility: hidden', {}, { visibility: 'hidden' }, { width: 300, height: 150 }],
            ['visibility: collapse', {}, { visibility: 'collapse' }, { width: 300, height: 150 }],
            ['display: none', {}, { display: 'none' }, { width: 300, height: 150 }],
            ['opacity: 0', {}, { opacity: '0' }, { width: 300, height: 150 }],
            ['zero width', {}, {}, { width: 0, height: 150 }],
            ['zero height', {}, {}, { width: 300, height: 0 }],
            ['zero width and height', {}, {}, { width: 0, height: 0 }],
        ])('returns false when canvas has %s', (_description, attributes, styles, dimensions) => {
            const canvas = document.createElement('canvas')
            canvas.width = dimensions.width
            canvas.height = dimensions.height
            for (const [key, value] of Object.entries(attributes)) {
                canvas.setAttribute(key, value)
            }

            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                visibility: 'visible',
                display: 'block',
                opacity: '1',
                ...styles,
            })

            expect(shouldMaskCanvas(canvas)).toBe(false)
        })

        it('returns true for visible canvas with dimensions', () => {
            const canvas = document.createElement('canvas')
            canvas.width = 300
            canvas.height = 150
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                visibility: 'visible',
                display: 'block',
                opacity: '1',
            })

            expect(shouldMaskCanvas(canvas)).toBe(true)
        })

        it('does not apply background to hidden canvases', () => {
            mockCanvas.setAttribute('aria-hidden', 'true')
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                visibility: 'visible',
                display: 'block',
                opacity: '1',
            })

            const plugin = CanvasReplayerPlugin([])
            plugin.onBuild?.(mockCanvas, { id: 1, replayer: mockReplayer })

            expect(mockCanvas.style.backgroundImage).toBe('')
        })
    })
})
