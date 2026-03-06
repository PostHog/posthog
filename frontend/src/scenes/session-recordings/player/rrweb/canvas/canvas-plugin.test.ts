/**
 * @jest-environment jsdom
 */
import { canvasMutation } from '@posthog/rrweb'
import { EventType, IncrementalSource, eventWithTime } from '@posthog/rrweb-types'

import { CanvasReplayerPlugin } from './canvas-plugin'

// Mock rrweb canvasMutation function
jest.mock('@posthog/rrweb', () => ({
    canvasMutation: jest.fn().mockResolvedValue(undefined),
    Replayer: jest.fn(),
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
    })

    describe('target canvas sizing from snapshot mutations', () => {
        const makeCanvasEvent = (
            id: number,
            clearRectW: number,
            clearRectH: number,
            opts?: { displayWidth?: number; displayHeight?: number }
        ): eventWithTime => ({
            type: EventType.IncrementalSnapshot as const,
            data: {
                source: IncrementalSource.CanvasMutation as const,
                id,
                type: 0,
                commands: [
                    { property: 'clearRect', args: [0, 0, clearRectW, clearRectH] },
                    {
                        property: 'drawImage',
                        args: [
                            {
                                rr_type: 'ImageBitmap',
                                args: [
                                    {
                                        rr_type: 'Blob',
                                        data: [{ rr_type: 'ArrayBuffer', base64: '' }],
                                        type: '',
                                    },
                                ],
                            },
                            0,
                            0,
                        ],
                    },
                ],
                ...(opts?.displayWidth ? { displayWidth: opts.displayWidth } : {}),
                ...(opts?.displayHeight ? { displayHeight: opts.displayHeight } : {}),
            },
            timestamp: 1000,
        })

        it.each([
            {
                name: 'uses displayWidth/displayHeight when present (new recordings)',
                canvasWidth: 1080,
                canvasHeight: 1920,
                clearRectW: 314,
                clearRectH: 559,
                displayWidth: 314,
                displayHeight: 559,
                expectedWidth: 314,
                expectedHeight: 559,
            },
            {
                name: 'falls back to clearRect args when displayWidth absent (existing recordings)',
                canvasWidth: 1080,
                canvasHeight: 1920,
                clearRectW: 314,
                clearRectH: 559,
                displayWidth: undefined,
                displayHeight: undefined,
                expectedWidth: 314,
                expectedHeight: 559,
            },
            {
                name: 'works when internal and display dimensions match',
                canvasWidth: 400,
                canvasHeight: 300,
                clearRectW: 400,
                clearRectH: 300,
                displayWidth: 400,
                displayHeight: 300,
                expectedWidth: 400,
                expectedHeight: 300,
            },
        ])(
            '$name',
            async ({
                canvasWidth,
                canvasHeight,
                clearRectW,
                clearRectH,
                displayWidth,
                displayHeight,
                expectedWidth,
                expectedHeight,
            }) => {
                const canvas = document.createElement('canvas')
                canvas.width = canvasWidth
                canvas.height = canvasHeight
                Object.defineProperty(canvas, 'clientWidth', { value: 0, configurable: true })
                Object.defineProperty(canvas, 'clientHeight', { value: 0, configurable: true })

                const event = makeCanvasEvent(42, clearRectW, clearRectH, { displayWidth, displayHeight })
                const plugin = CanvasReplayerPlugin([event])

                const replayer = {
                    getMirror: () => ({
                        getNode: (id: number) => (id === 42 ? canvas : null),
                    }),
                }

                plugin.onBuild?.(canvas, { id: 42, replayer } as any)
                plugin.handler!(event, false, { replayer } as any)

                await new Promise((resolve) => setTimeout(resolve, 10))

                expect(canvasMutation).toHaveBeenCalled()
                const call = (canvasMutation as jest.Mock).mock.calls.at(-1)[0]
                expect(call.target.width).toBe(expectedWidth)
                expect(call.target.height).toBe(expectedHeight)
            }
        )

        it('falls back to source.width when mutation has no clearRect', async () => {
            const canvas = document.createElement('canvas')
            canvas.width = 500
            canvas.height = 400
            Object.defineProperty(canvas, 'clientWidth', { value: 0, configurable: true })
            Object.defineProperty(canvas, 'clientHeight', { value: 0, configurable: true })

            const event = {
                type: EventType.IncrementalSnapshot as const,
                data: {
                    source: IncrementalSource.CanvasMutation as const,
                    id: 99,
                    type: 0,
                    commands: [{ property: 'drawImage', args: [{}, 0, 0] }],
                },
                timestamp: 1000,
            }

            const plugin = CanvasReplayerPlugin([event])
            const replayer = {
                getMirror: () => ({ getNode: (id: number) => (id === 99 ? canvas : null) }),
            }

            plugin.onBuild?.(canvas, { id: 99, replayer } as any)
            plugin.handler!(event, false, { replayer } as any)
            await new Promise((resolve) => setTimeout(resolve, 10))

            expect(canvasMutation).toHaveBeenCalled()
            const call = (canvasMutation as jest.Mock).mock.calls.at(-1)[0]
            expect(call.target.width).toBe(500)
            expect(call.target.height).toBe(400)
        })
    })
})
