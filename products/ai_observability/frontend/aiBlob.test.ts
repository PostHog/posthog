import { parseAiBlobPointer, resolveAiBlobUrl, resolveDataUri } from './aiBlob'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))

const HASH = 'a'.repeat(64)
const POINTER = `phaiblob://v1/sha256/${HASH}?mime=image%2Fpng&size=131072`

describe('aiBlob', () => {
    it('parses a pointer', () => {
        expect(parseAiBlobPointer(POINTER)).toEqual({
            version: 'v1',
            algo: 'sha256',
            hash: HASH,
            mime: 'image/png',
            size: 131072,
        })
    })

    it('resolves a pointer to the environment endpoint', () => {
        expect(resolveAiBlobUrl(POINTER, 1)).toBe(`/api/projects/1/ai_blob/v1/sha256/${HASH}`)
    })

    it.each([
        ['http url', 'https://example.com/a.png'],
        ['data uri', 'data:image/png;base64,AAAA'],
        ['plain text', 'hello'],
        ['bad hash', 'phaiblob://v1/sha256/xyz?mime=a&size=1'],
        ['unknown algo', `phaiblob://v1/md5/${HASH}?mime=a&size=1`],
        ['old scheme', `phblob://v1/sha256/${HASH}?mime=a&size=1`],
    ])('passes through unchanged: %s', (_name, value) => {
        expect(parseAiBlobPointer(value)).toBeNull()
        expect(resolveAiBlobUrl(value, 1)).toBe(value)
    })

    it('passes through when teamId is missing', () => {
        expect(resolveAiBlobUrl(POINTER, null)).toBe(POINTER)
    })

    it.each([
        ['image/png', `data:image/png;base64,${POINTER}`],
        ['application/pdf', `data:application/pdf;base64,${POINTER}`],
    ])('resolves a pointer that a recipe wrapped in a %s data uri', (_mime, wrapped) => {
        expect(parseAiBlobPointer(wrapped)).toMatchObject({ hash: HASH })
        expect(resolveAiBlobUrl(wrapped, 1)).toBe(`/api/projects/1/ai_blob/v1/sha256/${HASH}`)
    })

    it('resolves a pointer data field to the blob endpoint, ignoring the passed mime type', () => {
        expect(resolveDataUri(POINTER, 'image/png', 1)).toBe(`/api/projects/1/ai_blob/v1/sha256/${HASH}`)
    })

    it('builds a data: URI from raw base64 when the data field is not a pointer', () => {
        expect(resolveDataUri('AAAA', 'image/png', 1)).toBe('data:image/png;base64,AAAA')
    })

    describe('aiBlobRenderHandlers', () => {
        // jsdom implements neither PerformanceObserver nor the resource timeline, so the timing path
        // only runs against a stand-in observer that the test feeds entries to by hand.
        let aiBlob: typeof import('./aiBlob')
        let capture: jest.Mock
        let deliver: (entries: PerformanceEntry[]) => void

        function installFakeObserver(): (entries: PerformanceEntry[]) => void {
            type EntryList = { getEntries: () => PerformanceEntry[] }
            const callbacks: ((list: EntryList) => void)[] = []
            class FakePerformanceObserver {
                callback: (list: EntryList) => void
                constructor(callback: (list: EntryList) => void) {
                    this.callback = callback
                }
                observe(): void {
                    callbacks.push(this.callback)
                }
                disconnect(): void {}
            }
            Object.defineProperty(globalThis, 'PerformanceObserver', {
                value: FakePerformanceObserver,
                configurable: true,
                writable: true,
            })
            return (entries) => callbacks.forEach((callback) => callback({ getEntries: () => entries }))
        }

        function resourceEntry(url: string, transferSize: number, decodedBodySize: number): PerformanceEntry {
            const entry = {
                name: new URL(url, window.location.origin).toString(),
                entryType: 'resource',
                startTime: 0,
                duration: 0,
                transferSize,
                decodedBodySize,
                toJSON: () => ({}),
            }
            return entry
        }

        async function settle(): Promise<void> {
            await new Promise<void>((resolve) => setTimeout(resolve, 0))
        }

        beforeEach(() => {
            deliver = installFakeObserver()
            jest.resetModules()
            const posthogModule: { default: { capture: jest.Mock } } = require('posthog-js')
            capture = posthogModule.default.capture
            aiBlob = require('./aiBlob')
        })

        afterEach(() => {
            jest.useRealTimers()
            Reflect.deleteProperty(globalThis, 'PerformanceObserver')
        })

        it.each([
            ['a data uri', 'data:image/png;base64,AAAA'],
            ['an external url', 'https://example.com/a.png'],
            ['an unresolved pointer', POINTER],
        ])('attaches no handlers for %s', (_name, src) => {
            expect(aiBlob.aiBlobRenderHandlers(src, 'image')).toEqual({})
        })

        it.each<[string, 'before' | 'after', number, number, boolean]>([
            ['a network fetch whose entry lands after the load event', 'after', 2048, 4096, false],
            ['a cache hit, where a body is decoded but nothing crossed the network', 'after', 0, 4096, true],
            ['an entry the observer had already buffered before the load event', 'before', 1024, 2048, false],
        ])('reports the size and cache status of %s', async (_name, arrival, transfer, decoded, fromCache) => {
            const src = `/api/projects/1/ai_blob/v1/sha256/${'e'.repeat(64)}`
            const handlers = aiBlob.aiBlobRenderHandlers(src, 'image')
            const entries = [resourceEntry(src, transfer, decoded)]

            if (arrival === 'before') {
                deliver(entries)
                handlers.onLoad!()
            } else {
                handlers.onLoad!()
                deliver(entries)
            }
            await settle()

            expect(capture).toHaveBeenCalledWith('llma ai blob render', {
                outcome: 'success',
                media_kind: 'image',
                transfer_size_bytes: transfer,
                decoded_body_bytes: decoded,
                from_browser_cache: fromCache,
            })
        })

        it('reports the second render of a blob from its own entry, not the retained first one', async () => {
            const src = `/api/projects/1/ai_blob/v1/sha256/${'9'.repeat(64)}`
            const handlers = aiBlob.aiBlobRenderHandlers(src, 'image')

            deliver([resourceEntry(src, 2048, 4096)])
            handlers.onLoad!()
            await settle()

            handlers.onError!()
            deliver([resourceEntry(src, 0, 0)])
            await settle()

            expect(capture).toHaveBeenCalledWith(
                'llma ai blob render',
                expect.objectContaining({ outcome: 'error', transfer_size_bytes: 0, decoded_body_bytes: 0 })
            )
        })

        it('falls back to null timing when no entry arrives for the rendered blob', async () => {
            jest.useFakeTimers()
            const src = `/api/projects/1/ai_blob/v1/sha256/${'f'.repeat(64)}`
            const otherSrc = `/api/projects/1/ai_blob/v1/sha256/${'0'.repeat(64)}`

            aiBlob.aiBlobRenderHandlers(src, 'image').onLoad!()
            deliver([resourceEntry(otherSrc, 2048, 4096)])
            await jest.advanceTimersByTimeAsync(999)
            expect(capture).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(1)
            expect(capture).toHaveBeenCalledWith('llma ai blob render', {
                outcome: 'success',
                media_kind: 'image',
                transfer_size_bytes: null,
                decoded_body_bytes: null,
                from_browser_cache: null,
            })
        })

        it('captures success and error once per src, deduping repeat renders', async () => {
            const src = `/api/projects/1/ai_blob/v1/sha256/${'b'.repeat(64)}`
            const handlers = aiBlob.aiBlobRenderHandlers(src, 'image')
            handlers.onLoad!()
            handlers.onLoad!()
            handlers.onError!()
            deliver([resourceEntry(src, 2048, 4096)])
            await settle()

            expect(capture).toHaveBeenCalledTimes(2)
            expect(capture).toHaveBeenCalledWith(
                'llma ai blob render',
                expect.objectContaining({ outcome: 'success', transfer_size_bytes: 2048 })
            )
            expect(capture).toHaveBeenCalledWith(
                'llma ai blob render',
                expect.objectContaining({ outcome: 'error', transfer_size_bytes: 2048 })
            )
        })

        it('keeps capturing new srcs after the dedup cache fills up', async () => {
            jest.useFakeTimers()
            for (let i = 0; i < 1000; i++) {
                const src = `/api/projects/1/ai_blob/v1/sha256/${i.toString().padStart(64, '0')}`
                aiBlob.aiBlobRenderHandlers(src, 'image').onLoad!()
            }
            await jest.advanceTimersByTimeAsync(1000)
            capture.mockClear()

            const src = `/api/projects/1/ai_blob/v1/sha256/${'d'.repeat(64)}`
            aiBlob.aiBlobRenderHandlers(src, 'image').onLoad!()
            await jest.advanceTimersByTimeAsync(1000)

            expect(capture).toHaveBeenCalledWith(
                'llma ai blob render',
                expect.objectContaining({ outcome: 'success', media_kind: 'image' })
            )
        })

        it('signals audio success via canplay, which media elements fire instead of load', async () => {
            const src = `/api/projects/1/ai_blob/v1/sha256/${'c'.repeat(64)}`
            const handlers = aiBlob.aiBlobRenderHandlers(src, 'audio')
            expect(handlers.onLoad).toBeUndefined()
            handlers.onCanPlay!()
            deliver([resourceEntry(src, 512, 1024)])
            await settle()

            expect(capture).toHaveBeenCalledWith(
                'llma ai blob render',
                expect.objectContaining({ outcome: 'success', media_kind: 'audio', decoded_body_bytes: 1024 })
            )
        })
    })
})
