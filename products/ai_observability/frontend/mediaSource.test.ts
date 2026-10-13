import { isRedactedMediaSentinel, isRenderableMediaSource, redactedMediaKind } from './mediaSource'

const HASH = 'a'.repeat(64)
const POINTER = `phaiblob://v1/sha256/${HASH}?mime=image%2Fpng&size=131072`
const DATA_URI = 'data:image/png;base64,iVBORw0KGgo='
const REMOTE_URL = 'https://example.com/a.png'
const BASE64 = 'iVBORw0KGgo='

describe('mediaSource', () => {
    describe('redactedMediaKind', () => {
        it.each([
            ['python image sentinel', { type: 'image_url', image_url: { url: '[base64 image redacted]' } }, 'image'],
            ['node image sentinel', { type: 'image_url', image_url: { url: '[base64 image/png redacted]' } }, 'image'],
            [
                'file sentinel',
                { type: 'file', file: { file_data: '[base64 file redacted]', filename: 'doc.pdf' } },
                'file',
            ],
            [
                'anthropic image sentinel',
                { type: 'image', source: { type: 'base64', media_type: 'image/png', data: '[base64 image redacted]' } },
                'image',
            ],
            [
                'gemini image sentinel',
                { type: 'image', inline_data: { mime_type: 'image/png', data: '[base64 image redacted]' } },
                'image',
            ],
            ['Gemini URI sentinel', { type: 'image', uri: '[base64 image redacted]' }, 'image'],
            [
                'legacy image with a nested sentinel and competing sources',
                {
                    type: 'image',
                    uri: REMOTE_URL,
                    content: { image: REMOTE_URL, source: { data: '[base64 image redacted]' } },
                },
                'image',
            ],
            [
                'legacy image with a sentinel image source',
                { type: 'image', content: { image: '[base64 image redacted]', uri: REMOTE_URL } },
                'image',
            ],
            ['audio sentinel', { type: 'audio', mime_type: 'audio/wav', data: '[base64 audio redacted]' }, 'audio'],
            ['vercel image sentinel', { type: 'image', image: '[base64 image redacted]' }, 'image'],
            ['input_image sentinel', { type: 'input_image', image_url: '[base64 image redacted]' }, 'image'],
            [
                'sentinel wrapped in a data uri',
                { type: 'image_url', image_url: { url: 'data:image/png;base64,[base64 image redacted]' } },
                'image',
            ],
            [
                'MIME-less Gemini image sentinel',
                { type: 'image', data: '[base64 image redacted]', uri: REMOTE_URL },
                'image',
            ],
            [
                'MIME-less nested Gemini sentinel',
                { type: 'image', inline_data: { data: '[base64 image redacted]' }, uri: REMOTE_URL },
                'image',
            ],
            [
                'MIME-less camelCase sentinel',
                { type: 'image', inlineData: { data: '[base64 image redacted]' }, uri: REMOTE_URL },
                'image',
            ],
            [
                'MIME-less Anthropic sentinel',
                { type: 'image', source: { data: '[base64 image redacted]' }, uri: REMOTE_URL },
                'image',
            ],
        ])('flags %s as redacted', (_name, item, expected) => {
            expect(redactedMediaKind(item)).toBe(expected)
        })

        it.each([
            ['inline data uri', { type: 'image_url', image_url: { url: DATA_URI } }],
            ['offloaded blob pointer', { type: 'image_url', image_url: { url: POINTER } }],
            ['plain remote https url', { type: 'image_url', image_url: { url: REMOTE_URL } }],
            ['vercel image data uri', { type: 'image', image: DATA_URI }],
            [
                'anthropic raw base64',
                { type: 'image', source: { type: 'base64', media_type: 'image/png', data: BASE64 } },
            ],
            ['gemini raw base64', { type: 'image', inline_data: { mime_type: 'image/png', data: BASE64 } }],
            [
                'anthropic offloaded pointer',
                { type: 'image', source: { type: 'base64', media_type: 'image/png', data: POINTER } },
            ],
            ['gemini offloaded pointer', { type: 'image', inline_data: { mime_type: 'image/png', data: POINTER } }],
            ['audio raw base64', { type: 'audio', mime_type: 'audio/wav', data: BASE64 }],
            ['file as data uri', { type: 'file', file: { file_data: DATA_URI, filename: 'doc.pdf' } }],
            ['file as raw base64', { type: 'file', file: { file_data: BASE64, filename: 'doc.pdf' } }],
            ['unsupported Gemini URI', { type: 'image', uri: 'gs://example/image.png' }],
            ['MIME-less Gemini data', { type: 'image', data: BASE64 }],
            ['unsupported OpenAI URL', { type: 'image_url', image_url: { url: 'javascript:alert(1)' } }],
            ['unsupported input_image URL', { type: 'input_image', image_url: 'gs://example/image.png' }],
            ['unsupported Vercel URL', { type: 'image', image: 'nonsense' }],
            ['captured legacy image', { type: 'image', content: { image: REMOTE_URL, inlineData: { data: BASE64 } } }],
            [
                'legacy non-image MIME payload',
                {
                    type: 'image',
                    content: { mime_type: 'application/pdf', data: '[base64 file redacted]', uri: REMOTE_URL },
                },
            ],
            ['text part', { type: 'text', text: 'hello' }],
            ['unrelated part', { type: 'function', function: { name: 'get_weather' } }],
        ])('leaves %s renderable', (_name, item) => {
            expect(redactedMediaKind(item)).toBeNull()
        })
    })

    it('bounds legacy content inspection even when objects are cyclic', () => {
        const item: Record<string, unknown> = { type: 'image', image: REMOTE_URL }
        item.content = item
        expect(redactedMediaKind(item)).toBeNull()
        item.inlineData = { data: '[base64 image redacted]' }
        expect(redactedMediaKind(item)).toBe('image')
    })

    it('retains file classification for redacted non-image Gemini MIME payloads', () => {
        expect(redactedMediaKind({ type: 'image', mime_type: 'application/pdf', data: '[base64 file redacted]' })).toBe(
            'file'
        )
    })

    describe('isRedactedMediaSentinel', () => {
        it.each([
            '[base64 image redacted]',
            '[base64 image/png redacted]',
            '[base64 file redacted]',
            '[base64 audio/mpeg redacted]',
            '[base64 redacted]',
            'data:image/png;base64,[base64 image redacted]',
            'data:;base64,[base64 image redacted]',
            'data:image/png;charset=utf-8;base64,[base64 image redacted]',
            'DATA:IMAGE/PNG;BASE64,[base64 image redacted]',
        ])('matches %s', (value) => {
            expect(isRedactedMediaSentinel(value)).toBe(true)
        })

        it.each([DATA_URI, POINTER, REMOTE_URL, BASE64, 'nonsense'])('does not match %s', (value) => {
            expect(isRedactedMediaSentinel(value)).toBe(false)
        })
    })

    describe('isRenderableMediaSource', () => {
        it.each([DATA_URI, POINTER, REMOTE_URL, 'http://example.com/a.png'])('accepts %s', (value) => {
            expect(isRenderableMediaSource(value)).toBe(true)
        })

        it.each([
            '[base64 image redacted]',
            'data:image/png;base64,[base64 image redacted]',
            'data:;base64,[base64 image redacted]',
            'data:image/png;charset=utf-8;base64,[base64 image redacted]',
            'DATA:IMAGE/PNG;BASE64,[base64 image redacted]',
            BASE64,
            'nonsense',
            '',
        ])('rejects %s', (value) => {
            expect(isRenderableMediaSource(value)).toBe(false)
        })
    })
})
