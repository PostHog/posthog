import sharp, { type FormatEnum, type Sharp } from 'sharp'

import { UndecodableImageError, blurOnly } from './blur.ts'

describe('blur', () => {
    const swatch = (): Sharp => sharp({ create: { width: 8, height: 8, channels: 3, background: '#0af' } })

    // A capture can name a data URI `image/png` and put any bytes after the comma, and libvips
    // dispatches on magic bytes rather than that name, so the loader set is what actually bounds
    // which decoders user content can reach. image-input.ts allows only the PNG, JPEG, GIF and WebP
    // loaders. The rejection rows below cover every other loader in sharp's libvips that accepts a
    // buffer: TIFF, HEIF (AVIF and HEIC) and SVG.
    //
    // Loaders that libvips compiles in but that take no buffer input have no row here. That covers
    // CSV, matrix and the native VIPS format: a real `.v`/`.vips` buffer, built with the `vips` CLI,
    // fails to decode with the identical "unsupported image format" error whether or not the block is
    // applied, so no buffer can exercise that branch either way.
    it.each(['gif', 'png', 'jpeg', 'webp'])('decodes %s input', async (format) => {
        const bytes = await swatch()
            .toFormat(format as keyof FormatEnum)
            .toBuffer()

        await expect(blurOnly(bytes)).resolves.toBeInstanceOf(Buffer)
    })

    // An UltraHDR JPEG (for example from an Android camera) carries an ISO 21496-1 gain map after the
    // primary image. libvips gives such a file to its UltraHDR loader when that loader is available,
    // and the allowlist blocks that loader, so this case proves that the file still decodes through
    // the plain JPEG loader, which ignores the gain map.
    it('decodes a JPEG that carries a gain map', async () => {
        // sharp 0.35.3 implements withGainMap(), but its type declarations do not include it.
        const gainMapped = swatch() as Sharp & { withGainMap: () => Sharp }
        const bytes = await gainMapped.withGainMap().jpeg().toBuffer()
        expect(bytes.includes('urn:iso:std:iso:ts:21496')).toBe(true)

        await expect(blurOnly(bytes)).resolves.toBeInstanceOf(Buffer)
    })

    // sharp's prebuilt libvips has no HEVC encoder, so the HEIC case relabels an AVIF file's major
    // (offset 8) and compatible (offset 16 on) ftyp brands as `heic`. The HEIF loader claims a buffer
    // by those brands, so the block has to reject it too.
    const heicBranded = async (): Promise<Buffer> => {
        const bytes = await swatch().avif().toBuffer()
        bytes.write('heic', 8, 'ascii')
        for (let offset = 16; offset + 4 <= bytes.readUInt32BE(0); offset += 4) {
            bytes.write('heic', offset, 'ascii')
        }
        return bytes
    }

    it.each([
        ['TIFF', () => swatch().tiff().toBuffer()],
        ['AVIF', () => swatch().avif().toBuffer()],
        ['HEIC', heicBranded],
        [
            'SVG',
            async () =>
                Buffer.from(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="#0af"/></svg>'
                ),
        ],
    ])('rejects %s input as an unsupported format', async (_format, encode) => {
        const error = await blurOnly(await encode()).catch((e: unknown) => e)

        expect(error).toBeInstanceOf(UndecodableImageError)
        expect(error).toMatchObject({ reason: 'unsupported_format' })
    })
})
