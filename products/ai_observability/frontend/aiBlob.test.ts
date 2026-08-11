import posthog from 'posthog-js'

import { aiBlobRenderHandlers, parseAiBlobPointer, resolveAiBlobUrl, resolveDataUri } from './aiBlob'

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
        beforeEach(() => {
            jest.mocked(posthog.capture).mockClear()
        })

        it.each([
            ['a data uri', 'data:image/png;base64,AAAA'],
            ['an external url', 'https://example.com/a.png'],
            ['an unresolved pointer', POINTER],
        ])('attaches no handlers for %s', (_name, src) => {
            expect(aiBlobRenderHandlers(src, 'image')).toEqual({})
        })

        it('captures success and error once per src, deduping repeat renders', () => {
            const src = `/api/projects/1/ai_blob/v1/sha256/${'b'.repeat(64)}`
            const handlers = aiBlobRenderHandlers(src, 'image')
            handlers.onLoad!()
            handlers.onLoad!()
            handlers.onError!()
            expect(posthog.capture).toHaveBeenCalledTimes(2)
            expect(posthog.capture).toHaveBeenCalledWith('llma ai blob render', {
                outcome: 'success',
                media_kind: 'image',
                transfer_size_bytes: null,
                decoded_body_bytes: null,
                from_browser_cache: null,
            })
            expect(posthog.capture).toHaveBeenCalledWith('llma ai blob render', {
                outcome: 'error',
                media_kind: 'image',
                transfer_size_bytes: null,
                decoded_body_bytes: null,
                from_browser_cache: null,
            })
        })

        it('keeps capturing new srcs after the dedup cache fills up', () => {
            for (let i = 0; i < 1000; i++) {
                const src = `/api/projects/1/ai_blob/v1/sha256/${i.toString().padStart(64, '0')}`
                aiBlobRenderHandlers(src, 'image').onLoad!()
            }
            jest.mocked(posthog.capture).mockClear()

            const src = `/api/projects/1/ai_blob/v1/sha256/${'d'.repeat(64)}`
            aiBlobRenderHandlers(src, 'image').onLoad!()

            expect(posthog.capture).toHaveBeenCalledWith(
                'llma ai blob render',
                expect.objectContaining({ outcome: 'success', media_kind: 'image' })
            )
        })

        it('signals audio success via canplay, which media elements fire instead of load', () => {
            const src = `/api/projects/1/ai_blob/v1/sha256/${'c'.repeat(64)}`
            const handlers = aiBlobRenderHandlers(src, 'audio')
            expect(handlers.onLoad).toBeUndefined()
            handlers.onCanPlay!()
            expect(posthog.capture).toHaveBeenCalledWith(
                'llma ai blob render',
                expect.objectContaining({ outcome: 'success', media_kind: 'audio' })
            )
        })
    })
})
