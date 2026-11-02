import { brotliCompressSync, deflateSync, gzipSync, zstdCompressSync } from 'node:zlib'

import {
    MAX_UNCOMPRESSED_IMAGE_BYTES,
    SUPPORTED_IMAGE_MEDIA_TYPES,
    imageBytesMatchMediaType,
    prepareFetchedImage,
} from './image-transport'

const AVIF_HEADER = Buffer.concat([
    Buffer.from([0x00, 0x00, 0x00, 0x18]),
    Buffer.from('ftypavif', 'ascii'),
    Buffer.alloc(4),
    Buffer.from('avifmif1', 'ascii'),
])

const imageHeaders = {
    'image/png': Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    'image/jpeg': Buffer.from([0xff, 0xd8, 0xff, 0xe0]),
    'image/gif': Buffer.from('GIF89a', 'ascii'),
    'image/webp': Buffer.from('RIFF\x04\x00\x00\x00WEBP', 'binary'),
    'image/svg+xml': Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>', 'utf8'),
} satisfies Record<(typeof SUPPORTED_IMAGE_MEDIA_TYPES)[number], Buffer>

describe('image transport', () => {
    test.each(SUPPORTED_IMAGE_MEDIA_TYPES)('accepts %s bytes that match the Kafka content-type', (contentType) => {
        expect(imageBytesMatchMediaType(imageHeaders[contentType], contentType)).toBe(true)
    })

    const utf16 = (text: string, bigEndian: boolean): Buffer => {
        const body = Buffer.from(text, 'utf16le')
        return Buffer.concat([Buffer.from(bigEndian ? [0xfe, 0xff] : [0xff, 0xfe]), bigEndian ? body.swap16() : body])
    }
    const W3C_DOCTYPE =
        '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'

    test.each([
        ['a prolog before the root', `\uFEFF<?xml version="1.0"?>\n<!-- icon -->\n${W3C_DOCTYPE}\n<svg>`, true],
        ['a UTF-16LE document', utf16('<?xml version="1.0" encoding="UTF-16"?><svg/>', false), true],
        ['a UTF-16BE document', utf16('<svg/>', true), true],
        ['a prefixed root bound to the SVG namespace', '<s:svg xmlns:s="http://www.w3.org/2000/svg"/>', true],
        ['a prefixed root bound to another namespace', '<s:svg xmlns:s="http://example.com/ns"/>', false],
        ['an HTML page', '<!DOCTYPE html><html><svg></svg></html>', false],
        ['a root that only starts with svg', '<svgx/>', false],
        ['an unclosed comment', '<!-- <svg/>', false],
        ['a doctype with an internal subset', '<!DOCTYPE svg [<!ENTITY a "b">]><svg/>', false],
        [
            'a quoted literal that hides a subset',
            '<!DOCTYPE svg SYSTEM "><svg " [<!ENTITY x "s">]><svg>&x;</svg>',
            false,
        ],
        ['a doctype that names another DTD', '<!DOCTYPE svg SYSTEM "https://example.com/evil.dtd"><svg/>', false],
    ])('reads %s as SVG or not', (_case, document, isSvg) => {
        const bytes = typeof document === 'string' ? Buffer.from(document, 'utf8') : document
        expect(imageBytesMatchMediaType(bytes, 'image/svg+xml')).toBe(isSvg)
    })

    test.each([
        ['gzip', gzipSync],
        ['deflate', deflateSync],
        ['br', brotliCompressSync],
        ['zstd', zstdCompressSync],
    ] as const)('decodes %s response bytes before validating the image', async (contentEncoding, compress) => {
        const png = imageHeaders['image/png']

        await expect(prepareFetchedImage(compress(png), 'image/png', contentEncoding)).resolves.toEqual(png)
    })

    it('decodes stacked content codings in reverse application order', async () => {
        const png = imageHeaders['image/png']
        const encoded = brotliCompressSync(gzipSync(png))

        await expect(prepareFetchedImage(encoded, 'image/png', 'gzip, br')).resolves.toEqual(png)
    })

    it('rejects more than four content coding layers', async () => {
        await expect(
            prepareFetchedImage(
                imageHeaders['image/png'],
                'image/png',
                'identity, identity, identity, identity, identity'
            )
        ).rejects.toMatchObject({
            reason: 'content_encoding_too_deep',
            message: 'content-encoding exceeds 4 codings',
        })
    })

    it('stops decompression when the decoded bytes cross the 20 MiB cap', async () => {
        const compressed = gzipSync(Buffer.alloc(MAX_UNCOMPRESSED_IMAGE_BYTES + 1))

        await expect(prepareFetchedImage(compressed, 'image/png', 'gzip')).rejects.toMatchObject({
            reason: 'decoded_too_large',
            message: `decoded image exceeds ${MAX_UNCOMPRESSED_IMAGE_BYTES} bytes`,
        })
    })

    it.each([
        ['an unsupported content coding', imageHeaders['image/png'], 'compress', 'unsupported_content_encoding'],
        ['a malformed content coding list', imageHeaders['image/png'], 'gzip,', 'malformed_content_encoding'],
        ['compressed bytes that are malformed', Buffer.from('not gzip'), 'gzip', 'decompression_failed'],
    ] as const)('labels %s', async (_case, bytes, contentEncoding, reason) => {
        await expect(prepareFetchedImage(bytes, 'image/png', contentEncoding)).rejects.toMatchObject({ reason })
    })

    // A truncated body would otherwise store the prefix of an image, which still starts with a valid signature.
    test.each([
        ['gzip', gzipSync],
        ['deflate', deflateSync],
        ['br', brotliCompressSync],
        ['zstd', zstdCompressSync],
    ] as const)('rejects a %s body cut short', async (contentEncoding, compress) => {
        const png = Buffer.concat([imageHeaders['image/png'], Buffer.from('png body '.repeat(8))])
        const compressed = compress(png)

        for (const length of [compressed.length - 1, Math.floor(compressed.length / 2)]) {
            await expect(
                prepareFetchedImage(compressed.subarray(0, length), 'image/png', contentEncoding)
            ).rejects.toMatchObject({ reason: 'decompression_failed' })
        }
    })

    it('rejects a zstd body with a second frame, which the decoder would drop', async () => {
        const png = imageHeaders['image/png']
        const encoded = Buffer.concat([zstdCompressSync(png), zstdCompressSync(Buffer.from('tail'))])

        await expect(prepareFetchedImage(encoded, 'image/png', 'zstd')).rejects.toMatchObject({
            reason: 'decompression_failed',
        })
    })

    it('rejects bytes that do not match the declared media type', async () => {
        await expect(prepareFetchedImage(imageHeaders['image/jpeg'], 'image/png', undefined)).rejects.toMatchObject({
            reason: 'content_type_mismatch',
            message: 'image bytes do not match content-type image/png',
        })
    })

    it.each([
        ['a missing content-type', imageHeaders['image/png'], undefined, 'missing_content_type'],
        ['a BMP content-type', Buffer.from('BM', 'ascii'), 'image/bmp', 'unsupported_content_type'],
        ['an AVIF content-type', AVIF_HEADER, 'image/avif', 'unsupported_content_type'],
    ] as const)('labels %s', async (_case, bytes, contentType, reason) => {
        await expect(prepareFetchedImage(bytes, contentType, undefined)).rejects.toMatchObject({ reason })
    })
})
