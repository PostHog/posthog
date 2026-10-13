/**
 * @jest-environment jsdom
 */
import { canvasMutation } from 'posthog-js/rrweb'
import { EventType, IncrementalSource, eventWithTime } from 'posthog-js/rrweb-types'

import { CanvasMutationError, CanvasReplayerPlugin } from './canvas-plugin'

// Mock rrweb canvasMutation function
jest.mock('posthog-js/rrweb', () => ({
    canvasMutation: jest.fn().mockResolvedValue(undefined),
    Replayer: jest.fn(),
}))

// Polyfill APIs not available in jsdom
globalThis.createImageBitmap = jest.fn().mockResolvedValue({})

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
        const renderFrame = async (computedWidth: string, computedHeight: string): Promise<HTMLImageElement> => {
            ;(window.getComputedStyle as jest.Mock).mockReturnValue({
                width: computedWidth,
                height: computedHeight,
                display: 'block',
                getPropertyValue: jest.fn(() => ''),
            })
            // A 220x110 canvas under an ancestor with `transform: scale(0.5)`.
            mockCanvas.getBoundingClientRect = jest.fn(() => ({ width: 110, height: 55 }) as DOMRect)
            mockCanvas.toBlob = jest.fn((callback) => callback(new Blob(['frame'], { type: 'image/webp' })))
            const event = {
                type: EventType.IncrementalSnapshot as const,
                data: {
                    source: IncrementalSource.CanvasMutation as const,
                    id: 1,
                    type: 0,
                    commands: [{ property: 'drawImage', args: [{}, 0, 0] }],
                },
                timestamp: 1000,
            }

            const plugin = CanvasReplayerPlugin([event])
            plugin.onBuild?.(mockCanvas, { id: 1, replayer: mockReplayer })
            plugin.handler!(event, false, { replayer: mockReplayer })
            await new Promise((resolve) => setTimeout(resolve, 10))
            mockImage.dispatchEvent(new Event('load'))
            return mockImage
        }

        it.each([
            { name: 'ignores ancestor transforms', width: '220px', height: '110px', expected: ['220px', '110px'] },
            { name: 'keeps percentage sizes', width: '100%', height: '100%', expected: ['100%', '100%'] },
            { name: 'keeps mixed sizes', width: '100%', height: '200px', expected: ['100%', '200px'] },
            { name: 'falls back to the drawing buffer', width: '', height: '2px', expected: ['300px', '150px'] },
        ])('$name', async ({ width, height, expected }) => {
            const image = await renderFrame(width, height)

            expect([image.style.width, image.style.height]).toEqual(expected)
            expect(mockParent.contains(image)).toBe(true)
        })

        it('creates plugin with required methods', () => {
            const plugin = CanvasReplayerPlugin([])

            expect(plugin.onBuild).toBeTruthy()
            expect(plugin.handler).toBeTruthy()
            expect(typeof plugin.onBuild).toBe('function')
            expect(typeof plugin.handler).toBe('function')
            expect(typeof plugin.destroy).toBe('function')
        })
    })

    describe('destroy', () => {
        it('can be called safely after onBuild', () => {
            const plugin = CanvasReplayerPlugin([])
            const canvas = document.createElement('canvas')

            plugin.onBuild?.(canvas, { id: 1, replayer: mockReplayer })

            expect(() => plugin.destroy()).not.toThrow()
        })

        it('can be called multiple times safely', () => {
            const plugin = CanvasReplayerPlugin([])

            expect(() => {
                plugin.destroy()
                plugin.destroy()
            }).not.toThrow()
        })
    })

    describe('reconstructed image attribute copying', () => {
        it.each(['onload', 'onerror', 'onclick', 'onmouseover', 'onanimationstart', 'ontoggle'])(
            'does not copy the %s event handler attribute from the recorded canvas',
            (handlerName) => {
                const canvas = document.createElement('canvas')
                canvas.setAttribute(handlerName, 'globalThis.__canvasXss = true')
                canvas.setAttribute('class', 'my-canvas')

                const plugin = CanvasReplayerPlugin([])
                plugin.onBuild?.(canvas, { id: 1, replayer: mockReplayer } as any)

                expect(mockImage.hasAttribute(handlerName)).toBe(false)
                // benign attributes are still copied so playback styling is preserved
                expect(mockImage.getAttribute('class')).toBe('my-canvas')
            }
        )

        it.each(['src', 'srcset'])(
            'does not copy the %s resource-loading attribute from the recorded canvas',
            (attrName) => {
                const canvas = document.createElement('canvas')
                canvas.setAttribute(attrName, 'https://attacker.example/x')
                canvas.setAttribute('class', 'my-canvas')

                const plugin = CanvasReplayerPlugin([])
                plugin.onBuild?.(canvas, { id: 1, replayer: mockReplayer } as any)

                expect(mockImage.hasAttribute(attrName)).toBe(false)
                expect(mockImage.getAttribute('class')).toBe('my-canvas')
            }
        )
    })

    describe('reconstructed image document', () => {
        it('builds the image in the document that holds the recorded canvas', () => {
            const replayDocument = document.implementation.createHTMLDocument()
            const canvas = replayDocument.createElement('canvas')
            replayDocument.body.appendChild(canvas)

            const created: Element[] = []
            const createInReplayDocument = replayDocument.createElement.bind(replayDocument)
            jest.spyOn(replayDocument, 'createElement').mockImplementation((tagName: string) => {
                const element = createInReplayDocument(tagName)
                created.push(element)
                return element
            })

            const plugin = CanvasReplayerPlugin([])
            plugin.onBuild?.(canvas, { id: 1, replayer: mockReplayer } as any)

            const image = created.find((element) => element.tagName === 'IMG')
            expect(image?.ownerDocument).toBe(replayDocument)
        })
        it('builds a new image when a seek rebuilds the canvas in a new document', () => {
            const firstDocument = document.implementation.createHTMLDocument()
            const rebuiltDocument = document.implementation.createHTMLDocument()
            const firstCanvas = firstDocument.createElement('canvas')
            const rebuiltCanvas = rebuiltDocument.createElement('canvas')
            rebuiltDocument.body.appendChild(rebuiltCanvas)

            const plugin = CanvasReplayerPlugin([])
            plugin.onBuild?.(firstCanvas, { id: 1, replayer: mockReplayer } as any)
            const createImage = jest.spyOn(rebuiltDocument, 'createElement')
            plugin.onBuild?.(rebuiltCanvas, { id: 1, replayer: mockReplayer } as any)

            expect(createImage).toHaveBeenCalledWith('img')
            expect(createImage.mock.results[0].value.ownerDocument).toBe(rebuiltDocument)
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

    describe('canvas mutation error reporting', () => {
        const reportCanvasMutationFailure = async (thrown: unknown): Promise<jest.Mock> => {
            const canvas = document.createElement('canvas')
            const event = {
                type: EventType.IncrementalSnapshot as const,
                data: {
                    source: IncrementalSource.CanvasMutation as const,
                    id: 7,
                    type: 1,
                    commands: [{ property: 'drawArrays', args: [0, 0, 3] }],
                },
                timestamp: 1000,
            }
            const onError = jest.fn()
            // rrweb calls errorHandler from a catch after an await, never synchronously.
            const handled = new Promise<void>((resolve) => {
                ;(canvasMutation as jest.Mock).mockImplementationOnce(async ({ mutation, errorHandler }) => {
                    await Promise.resolve()
                    errorHandler(mutation, thrown)
                    resolve()
                })
            })

            const plugin = CanvasReplayerPlugin([event], onError)
            const replayer = { getMirror: () => ({ getNode: (id: number) => (id === 7 ? canvas : null) }) }
            plugin.onBuild?.(canvas, { id: 7, replayer } as any)
            plugin.handler!(event, false, { replayer } as any)
            await handled
            return onError
        }

        it('reports the error rrweb passes, not the mutation', async () => {
            const thrown = new TypeError('drawImage failed')

            const onError = await reportCanvasMutationFailure(thrown)

            expect(onError).toHaveBeenCalledTimes(1)
            const [reported, context] = onError.mock.calls[0]
            expect(reported).toBe(thrown)
            expect(context).toEqual({ canvas_node_id: 7, canvas_context: 'WebGL' })
        })

        it('wraps a non-Error value with the canvas context', async () => {
            const onError = await reportCanvasMutationFailure('context lost')

            expect(onError).toHaveBeenCalledTimes(1)
            const [reported, context] = onError.mock.calls[0]
            expect(reported).toBeInstanceOf(CanvasMutationError)
            expect(reported.message).toBe('Canvas mutation failed in WebGL context: context lost')
            expect(context).toEqual({ canvas_node_id: 7, canvas_context: 'WebGL' })
        })
    })
})
