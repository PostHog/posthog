import { brotliCompressSync, deflateSync, gzipSync, zstdCompressSync } from 'node:zlib'

import {
    InvalidImageTransportError,
    MAX_UNCOMPRESSED_IMAGE_BYTES,
    SUPPORTED_IMAGE_MEDIA_TYPES,
    imageBytesMatchMediaType,
    prepareFetchedImage,
} from './image-transport'

const imageHeaders = {
    'image/png': Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    'image/jpeg': Buffer.from([0xff, 0xd8, 0xff, 0xe0]),
    'image/gif': Buffer.from('GIF89a', 'ascii'),
    'image/webp': Buffer.from('RIFF\x04\x00\x00\x00WEBP', 'binary'),
    'image/avif': Buffer.concat([
        Buffer.from([0x00, 0x00, 0x00, 0x18]),
        Buffer.from('ftypavif', 'ascii'),
        Buffer.alloc(4),
        Buffer.from('avifmif1', 'ascii'),
    ]),
} satisfies Record<(typeof SUPPORTED_IMAGE_MEDIA_TYPES)[number], Buffer>

describe('image transport', () => {
    test.each(SUPPORTED_IMAGE_MEDIA_TYPES)('accepts %s bytes that match the Kafka content-type', (contentType) => {
        expect(imageBytesMatchMediaType(imageHeaders[contentType], contentType)).toBe(true)
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
        ).rejects.toThrow('content-encoding exceeds 4 codings')
    })

    it('stops decompression when the decoded bytes cross the 20 MiB cap', async () => {
        const compressed = gzipSync(Buffer.alloc(MAX_UNCOMPRESSED_IMAGE_BYTES + 1))

        await expect(prepareFetchedImage(compressed, 'image/png', 'gzip')).rejects.toThrow(
            `decoded image exceeds ${MAX_UNCOMPRESSED_IMAGE_BYTES} bytes`
        )
    })

    it.each([
        ['an unsupported content coding', imageHeaders['image/png'], 'compress'],
        ['a malformed content coding list', imageHeaders['image/png'], 'gzip,'],
        ['compressed bytes that are malformed', Buffer.from('not gzip'), 'gzip'],
    ])('rejects %s', async (_case, bytes, contentEncoding) => {
        await expect(prepareFetchedImage(bytes, 'image/png', contentEncoding)).rejects.toBeInstanceOf(
            InvalidImageTransportError
        )
    })

    it('rejects bytes that do not match the declared media type', async () => {
        await expect(prepareFetchedImage(imageHeaders['image/jpeg'], 'image/png', undefined)).rejects.toThrow(
            'image bytes do not match content-type image/png'
        )
    })

    it('rejects BMP images', async () => {
        await expect(prepareFetchedImage(Buffer.from('BM', 'ascii'), 'image/bmp', undefined)).rejects.toThrow(
            'unsupported content-type: image/bmp'
        )
    })
})
