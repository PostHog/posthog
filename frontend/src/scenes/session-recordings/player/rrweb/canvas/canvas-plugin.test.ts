import { EventType, IncrementalSource } from '@posthog/rrweb-types'

import { CanvasReplayerPlugin } from './canvas-plugin'

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
        jest.spyOn(document, 'createElement').mockImplementation((tagName) => {
            if (tagName === 'img') {
                return mockImage
            }
            return document.createElement(tagName)
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
                getPropertyValue: jest.fn((prop) => {
                    if (prop === 'margin') {
                        return '0px'
                    }
                    if (prop === 'padding') {
                        return '0px'
                    }
                    return ''
                }),
            })

            const plugin = CanvasReplayerPlugin([])

            // Simulate onBuild - canvas replacement with image
            plugin.onBuild?.(mockCanvas, { id: 1, replayer: mockReplayer })

            // Create canvas mutation event
            const mockEvent = {
                type: EventType.IncrementalSnapshot,
                data: {
                    source: IncrementalSource.CanvasMutation,
                    id: 1,
                },
                timestamp: 1000,
            }

            // Mock canvas mutation function
            const mockCanvasMutation = jest.fn().mockResolvedValue(undefined)
            jest.doMock('@posthog/rrweb', () => ({
                canvasMutation: mockCanvasMutation,
            }))

            // Trigger canvas mutation handler
            plugin.handler?.(mockEvent as any, false, { replayer: mockReplayer })

            // Wait for async operations to complete
            await new Promise((resolve) => setTimeout(resolve, 10))

            // Verify percentage dimensions are preserved
            expect(mockImage.style.width).toBe('100%')
            expect(mockImage.style.height).toBe('100%')
        })

        it('uses pixel dimensions for fixed-size canvases', async () => {
            // Mock fixed-size canvas
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

            const plugin = CanvasReplayerPlugin([])

            plugin.onBuild?.(mockCanvas, { id: 2, replayer: mockReplayer })

            const mockEvent = {
                type: EventType.IncrementalSnapshot,
                data: {
                    source: IncrementalSource.CanvasMutation,
                    id: 2,
                },
                timestamp: 1000,
            }

            plugin.handler?.(mockEvent as any, false, { replayer: mockReplayer })

            await new Promise((resolve) => setTimeout(resolve, 10))

            // Verify pixel dimensions are used
            expect(mockImage.style.width).toBe('400px')
            expect(mockImage.style.height).toBe('200px')
        })

        it('falls back to canvas drawing buffer when measurements fail', async () => {
            // Mock empty computed styles
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                width: '',
                height: '',
                display: 'block',
                getPropertyValue: jest.fn(() => ''),
            })

            // Mock all measurement methods to return tiny/invalid values
            mockCanvas.getBoundingClientRect = jest.fn(() => ({
                width: 2,
                height: 1,
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

            const plugin = CanvasReplayerPlugin([])

            plugin.onBuild?.(mockCanvas, { id: 3, replayer: mockReplayer })

            const mockEvent = {
                type: EventType.IncrementalSnapshot,
                data: {
                    source: IncrementalSource.CanvasMutation,
                    id: 3,
                },
                timestamp: 1000,
            }

            plugin.handler?.(mockEvent as any, false, { replayer: mockReplayer })

            await new Promise((resolve) => setTimeout(resolve, 10))

            // Should fall back to canvas drawing buffer dimensions (300x150)
            expect(mockImage.style.width).toBe('300px')
            expect(mockImage.style.height).toBe('150px')
        })

        it('handles mixed percentage and pixel sizing', async () => {
            // Mock mixed sizing: percentage width, pixel height
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                width: '100%',
                height: '200px',
                display: 'block',
                getPropertyValue: jest.fn(() => ''),
            })

            const plugin = CanvasReplayerPlugin([])

            plugin.onBuild?.(mockCanvas, { id: 4, replayer: mockReplayer })

            const mockEvent = {
                type: EventType.IncrementalSnapshot,
                data: {
                    source: IncrementalSource.CanvasMutation,
                    id: 4,
                },
                timestamp: 1000,
            }

            plugin.handler?.(mockEvent as any, false, { replayer: mockReplayer })

            await new Promise((resolve) => setTimeout(resolve, 10))

            // Should preserve mixed sizing
            expect(mockImage.style.width).toBe('100%')
            expect(mockImage.style.height).toBe('200px')
        })
    })
})
