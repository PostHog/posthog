import { createHash } from 'crypto'

import { parseJSON } from '~/common/utils/json-parse'

import { extractBlobs } from './detect'
import { parseBlobPointer } from './pointer'

const PNG_BYTES = Buffer.alloc(20000, 7)
const PNG_B64 = PNG_BYTES.toString('base64')
const PNG_HASH = createHash('sha256').update(PNG_BYTES).digest('hex')
const JPEG_BYTES = Buffer.alloc(20000, 9)
const JPEG_B64 = JPEG_BYTES.toString('base64')
const JPEG_HASH = createHash('sha256').update(JPEG_BYTES).digest('hex')
const AUDIO_BYTES = Buffer.alloc(98304, 3)
const AUDIO_B64 = AUDIO_BYTES.toString('base64')
const OPTS = { minBase64Length: 8192 }

describe('extractBlobs', () => {
    it('replaces an openai image data-URI with a pointer and captures exact bytes', () => {
        const input = [
            {
                role: 'user',
                content: [
                    { type: 'text', text: 'what is this?' },
                    { type: 'image_url', image_url: { url: `data:image/png;base64,${PNG_B64}`, detail: 'high' } },
                ],
            },
        ]
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(result.blobs[0]).toMatchObject({ mime: 'image/png', hash: PNG_HASH, detector: 'data_uri' })
        expect(result.blobs[0].bytes.equals(PNG_BYTES)).toBe(true)
        const rewritten = result.value as typeof input
        const pointer = parseBlobPointer(rewritten[0].content[1].image_url!.url)
        expect(pointer).toEqual({ algo: 'sha256', hash: PNG_HASH, mime: 'image/png', size: PNG_BYTES.length })
        expect(result.savedChars).toBe(
            input[0].content[1].image_url!.url.length - rewritten[0].content[1].image_url!.url.length
        )
        expect(rewritten[0].content[0].text).toBe('what is this?')
        expect(rewritten[0].content[1].image_url!.detail).toBe('high')
        expect(input[0].content[1].image_url!.url.startsWith('data:')).toBe(true) // input not mutated
    })

    it.each([
        [
            'anthropic_source',
            { type: 'image', source: { type: 'base64', media_type: 'image/png', data: PNG_B64 } },
            (v: unknown): string => (v as { source: { data: string } }).source.data,
        ],
        [
            'gemini_inline_data camelCase',
            { inlineData: { mimeType: 'image/png', data: PNG_B64 } },
            (v: unknown): string => (v as { inlineData: { data: string } }).inlineData.data,
        ],
        [
            'gemini_inline_data snake_case',
            { inline_data: { mime_type: 'image/png', data: PNG_B64 } },
            (v: unknown): string => (v as { inline_data: { data: string } }).inline_data.data,
        ],
    ])('extracts %s shapes, replacing only the data field', (_name, input, getData) => {
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(result.blobs[0].hash).toBe(PNG_HASH)
        expect(result.blobs[0].mime).toBe('image/png')
        const pointer = parseBlobPointer(getData(result.value))
        expect(pointer?.hash).toBe(PNG_HASH)
    })

    it('extracts openai input_audio with mime from format', () => {
        const input = { type: 'input_audio', input_audio: { data: PNG_B64, format: 'wav' } }
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(result.blobs[0].mime).toBe('audio/wav')
        expect(result.blobs[0].detector).toBe('openai_input_audio')
    })

    it('offloads {data, format} outside input_audio via blind path, not the audio detector', () => {
        const input = { report: { data: PNG_B64, format: 'summary' } }
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(result.blobs[0]).toMatchObject({ detector: 'raw_base64', mime: 'application/octet-stream' })
    })

    it('offloads a provider shape with an oversized mime via blind path with a safe mime', () => {
        const input = { source: { type: 'base64', media_type: `image/${'x'.repeat(300)}`, data: PNG_B64 } }
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(result.blobs[0]).toMatchObject({ detector: 'raw_base64', mime: 'application/octet-stream' })
    })

    it('dedupes the same content arriving via different shapes to one blob', () => {
        const input = [
            { image_url: { url: `data:image/png;base64,${PNG_B64}` } },
            { source: { type: 'base64', media_type: 'image/png', data: PNG_B64 } },
        ]
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        const rewritten = result.value as [{ image_url: { url: string } }, { source: { data: string } }]
        expect(parseBlobPointer(rewritten[0].image_url.url)?.hash).toBe(PNG_HASH)
        expect(parseBlobPointer(rewritten[1].source.data)?.hash).toBe(PNG_HASH)
    })

    it('leaves blobs below the size floor inline and counts them', () => {
        const small = Buffer.alloc(100, 1).toString('base64')
        const input = { image_url: { url: `data:image/png;base64,${small}` } }
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(0)
        expect(result.belowFloorCount).toBe(1)
        expect(result.belowFloorBytes).toBeGreaterThan(0)
        expect((result.value as { image_url: { url: string } }).image_url.url).toBe(`data:image/png;base64,${small}`)
    })

    it.each([
        ['plain text payload', { role: 'user', content: 'just text' }],
        ['http url', { image_url: { url: 'https://example.com/img.png' } }],
        ['existing pointer', { image_url: { url: `phaiblob://v1/sha256/${'a'.repeat(64)}?mime=image%2Fpng&size=1` } }],
        ['non-base64 data field', { source: { type: 'base64', media_type: 'image/png', data: 'not base64 !!!' } }],
        [
            'long plain text in a mime-shaped object',
            { inline_data: { mime_type: 'text/plain', data: 'lorem ipsum dolor sit amet '.repeat(400) } },
        ],
        [
            'padding-misaligned base64 charset string',
            { inline_data: { mime_type: 'text/plain', data: 'A'.repeat(8193) } },
        ],
        ['oversized mime in a data URI', { image_url: { url: `data:image/${'x'.repeat(300)};base64,${PNG_B64}` } }],
    ])('passes through untouched: %s', (_name, input) => {
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(0)
        expect(result.value).toEqual(input)
    })

    it.each([
        ['crlf header injection', 'mp3\r\nX-Injected: 1'],
        ['non-latin1 characters', 'mp3🎵'],
        ['spaces', 'mp3 audio'],
    ])('offloads input_audio with a hostile format via blind path, ignoring the format (%s)', (_name, format) => {
        const input = { type: 'input_audio', input_audio: { data: PNG_B64, format } }
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(result.blobs[0]).toMatchObject({ detector: 'raw_base64', mime: 'application/octet-stream' })
    })

    it.each([
        ['host blob above the floor', PNG_B64, 2],
        ['host blob below the floor', Buffer.alloc(100, 1).toString('base64'), 1],
    ])('rewrites sibling data URIs inside a matched provider shape (%s)', (_name, hostData, expectedBlobs) => {
        const input = {
            type: 'base64',
            media_type: 'image/png',
            data: hostData,
            preview: { image_url: { url: `data:image/jpeg;base64,${JPEG_B64}` } },
        }
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(expectedBlobs)
        const rewritten = result.value as typeof input
        expect(parseBlobPointer(rewritten.preview.image_url.url)?.hash).toBe(JPEG_HASH)
    })

    it('preserves a JSON-parsed __proto__ field during rewrites', () => {
        const input = parseJSON(`{"image_url":{"url":"data:image/png;base64,${PNG_B64}"},"__proto__":{"marker":1}}`)
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(JSON.stringify(result.value)).toContain('"__proto__":{"marker":1}')
        expect(Object.getPrototypeOf(result.value)).toBe(Object.prototype)
    })

    it('lowercases declared mimes so stored content types are canonical', () => {
        const input = { source: { type: 'base64', media_type: 'IMAGE/PNG', data: PNG_B64 } }
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(result.blobs[0].mime).toBe('image/png')
        expect(parseBlobPointer((result.value as typeof input).source.data)?.mime).toBe('image/png')
    })

    it('caps traversal depth instead of overflowing the stack on deeply nested payloads', () => {
        let deep: unknown = 'leaf'
        for (let i = 0; i < 100000; i++) {
            deep = [deep]
        }
        const input = { shallow: { image_url: { url: `data:image/png;base64,${PNG_B64}` } }, deep }
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect((result.value as { deep: unknown }).deep).toBe(deep)
    })

    it('leaves data URIs with non-canonical base64 inline instead of truncated-decoding them', () => {
        const url = `data:image/png;base64,AAAA=${PNG_B64}`
        const result = extractBlobs({ image_url: { url } }, OPTS)
        expect(result.blobs).toHaveLength(0)
        expect((result.value as { image_url: { url: string } }).image_url.url).toBe(url)
    })

    it('compacts whitespace-wrapped base64 inside data URIs and captures exact bytes', () => {
        const wrapped = PNG_B64.replace(/(.{76})/g, '$1\n')
        const result = extractBlobs({ image_url: { url: `data:image/png;base64,${wrapped}` } }, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(result.blobs[0].mime).toBe('image/png')
        expect(result.blobs[0].bytes.equals(PNG_BYTES)).toBe(true)
    })

    it('offloads shapeless raw base64 (openai audio output part) via the blind path', () => {
        const input = [
            {
                role: 'assistant',
                content: [
                    {
                        type: 'audio',
                        id: 'audio_6a5f3b1f',
                        expires_at: 1784629551,
                        transcript: 'The capital of France is Paris.',
                        data: AUDIO_B64,
                    },
                ],
            },
        ]
        const result = extractBlobs(input, OPTS)
        expect(result.blobs).toHaveLength(1)
        expect(result.blobs[0]).toMatchObject({ detector: 'raw_base64', mime: 'application/octet-stream' })
        expect(result.blobs[0].bytes.equals(AUDIO_BYTES)).toBe(true)
        const part = (result.value as typeof input)[0].content[0]
        expect(parseBlobPointer(part.data)?.mime).toBe('application/octet-stream')
        expect(part.transcript).toBe('The capital of France is Paris.')
    })

    it('leaves whitespace-wrapped bare base64 inline (blind path is byte-strict)', () => {
        // slice(60001) drops one char so the inserted newline keeps length % 4 === 0 —
        // the string must reach the full canonical scan, not die at the cheap length check.
        const wrapped = `${AUDIO_B64.slice(0, 60000)}\n${AUDIO_B64.slice(60001)}`
        const result = extractBlobs({ content: wrapped }, OPTS)
        expect(result.blobs).toHaveLength(0)
        expect((result.value as { content: string }).content).toBe(wrapped)
    })

    it('leaves sub-floor raw base64 inline without below-floor counting', () => {
        const embedding = Buffer.alloc(6144, 1).toString('base64')
        const result = extractBlobs({ content: embedding }, { minBase64Length: 20480 })
        expect(result.blobs).toHaveLength(0)
        expect(result.belowFloorCount).toBe(0)
        expect(result.value).toEqual({ content: embedding })
    })
})
